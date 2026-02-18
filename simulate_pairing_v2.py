#!/usr/bin/env python
"""
Simulate the pairing-v2 algorithm + Bradley-Terry ranking.
Port of frontend pairing-v2.ts logic to Python.
"""
import asyncio
import sys
import random
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple, Optional
from app.clients.supabase_db import supabase_client
from app.core.ranking import RankingManager


@dataclass
class SimSong:
    """Simulated song with stats."""
    song_id: str
    name: str
    bt_strength: float = 0.0
    local_elo: float = 1500.0
    comparison_count: int = 0


@dataclass
class ComparisonHistory:
    """Track which pairs have been compared."""
    compared_pairs: Set[str] = field(default_factory=set)


def make_pair_key(id_a: str, id_b: str) -> str:
    """Create a consistent pair key (sorted)."""
    return f"{id_a}:{id_b}" if id_a < id_b else f"{id_b}:{id_a}"


def get_strength(song: SimSong) -> float:
    """Get effective strength (θ)."""
    if song.bt_strength is not None:
        return song.bt_strength
    return (song.local_elo - 1500) / 173.72


def get_uncertainty(song: SimSong) -> float:
    """Higher = more uncertain = needs more comparisons."""
    return 1 / (song.comparison_count + 1)


def get_phase(songs: List[SimSong]) -> str:
    """Determine ranking phase based on comparison distribution."""
    counts = [s.comparison_count for s in songs]
    min_comps = min(counts)
    max_comps = max(counts)
    avg_comps = sum(counts) / len(songs)
    
    # ALWAYS stay in coverage if any song is severely under-compared
    if min_comps < 3:
        return "coverage"
    
    # If huge imbalance, go back to coverage
    if max_comps > min_comps * 3 and min_comps < 5:
        return "coverage"
    
    if avg_comps < 4:
        return "refinement"
    
    return "verification"


def select_coverage_pair(
    songs: List[SimSong], 
    history: ComparisonHistory
) -> Tuple[SimSong, SimSong]:
    """Coverage mode: prioritize under-compared songs."""
    sorted_songs = sorted(songs, key=lambda s: s.comparison_count)
    song_a = sorted_songs[0]
    
    for song_b in sorted_songs:
        if song_b.song_id == song_a.song_id:
            continue
        pair_key = make_pair_key(song_a.song_id, song_b.song_id)
        if pair_key not in history.compared_pairs:
            return (song_a, song_b) if random.random() < 0.5 else (song_b, song_a)
    
    # All pairs compared, pick least-compared alternative
    song_b = next(s for s in sorted_songs if s.song_id != song_a.song_id)
    return (song_a, song_b) if random.random() < 0.5 else (song_b, song_a)


def get_candidate_pairs(
    songs: List[SimSong],
    history: ComparisonHistory
) -> List[Dict]:
    """Get scored candidate pairs."""
    candidates = []
    
    for i, a in enumerate(songs):
        for b in songs[i+1:]:
            pair_key = make_pair_key(a.song_id, b.song_id)
            already_compared = pair_key in history.compared_pairs
            
            uncertainty_a = get_uncertainty(a)
            uncertainty_b = get_uncertainty(b)
            combined_uncertainty = uncertainty_a + uncertainty_b
            
            strength_diff = abs(get_strength(a) - get_strength(b))
            closeness_bonus = 1 / (strength_diff + 0.1) if combined_uncertainty < 0.5 else 0
            
            score = combined_uncertainty * 10 + closeness_bonus
            if already_compared:
                score *= 0.1  # Heavy penalty for repeats
            
            candidates.append({"a": a, "b": b, "score": score})
    
    return sorted(candidates, key=lambda x: -x["score"])


def select_refinement_pair(
    songs: List[SimSong],
    history: ComparisonHistory
) -> Tuple[SimSong, SimSong]:
    """Refinement mode: compare similar-strength uncertain songs."""
    candidates = get_candidate_pairs(songs, history)
    
    if not candidates:
        a, b = random.sample(songs, 2)
        return (a, b) if random.random() < 0.5 else (b, a)
    
    # Pick from top 5 with randomness
    top_n = min(5, len(candidates))
    selected = candidates[random.randint(0, top_n - 1)]
    a, b = selected["a"], selected["b"]
    return (a, b) if random.random() < 0.5 else (b, a)


def select_verification_pair(
    songs: List[SimSong],
    history: ComparisonHistory
) -> Tuple[SimSong, SimSong]:
    """Verification mode: confirm adjacent rankings."""
    sorted_songs = sorted(songs, key=lambda s: -get_strength(s))
    
    adjacent_pairs = []
    for i in range(len(sorted_songs) - 1):
        a = sorted_songs[i]
        b = sorted_songs[i + 1]
        gap = abs(get_strength(a) - get_strength(b))
        min_comps = min(a.comparison_count, b.comparison_count)
        pair_key = make_pair_key(a.song_id, b.song_id)
        compared = pair_key in history.compared_pairs
        
        gap_score = 1 / (gap + 0.1)
        uncertainty_score = 1 / (min_comps + 1)
        position_bonus = 2 if i < 10 else 1
        
        score = (gap_score + uncertainty_score * 2) * position_bonus
        if compared:
            score *= 0.3
        
        adjacent_pairs.append({"a": a, "b": b, "score": score})
    
    adjacent_pairs.sort(key=lambda x: -x["score"])
    
    top_n = min(3, len(adjacent_pairs))
    if top_n > 0:
        selected = adjacent_pairs[random.randint(0, top_n - 1)]
        a, b = selected["a"], selected["b"]
        return (a, b) if random.random() < 0.5 else (b, a)
    
    return (sorted_songs[0], sorted_songs[1])


def get_next_pair_v2(
    songs: List[SimSong],
    history: ComparisonHistory
) -> Optional[Tuple[SimSong, SimSong]]:
    """Main pairing function (port of pairing-v2.ts)."""
    if len(songs) < 2:
        return None
    
    phase = get_phase(songs)
    
    if phase == "coverage":
        return select_coverage_pair(songs, history)
    elif phase == "refinement":
        return select_refinement_pair(songs, history)
    else:
        return select_verification_pair(songs, history)


def simulate_duel(
    song_a: SimSong,
    song_b: SimSong,
    true_rankings: Dict[str, int],
    undefeated_ids: Set[str] = None
) -> str:
    """
    Simulate a duel outcome based on "true" rankings.
    The song with better true rank wins (with some noise for realism).
    Songs in undefeated_ids always win (100% win rate).
    """
    rank_a = true_rankings.get(song_a.song_id, 999)
    rank_b = true_rankings.get(song_b.song_id, 999)
    
    # Check if either song is undefeated (100% win rate)
    if undefeated_ids:
        a_undefeated = song_a.song_id in undefeated_ids
        b_undefeated = song_b.song_id in undefeated_ids
        
        if a_undefeated and not b_undefeated:
            return song_a.song_id
        if b_undefeated and not a_undefeated:
            return song_b.song_id
        # If both undefeated, use rankings
    
    # Better rank (lower number) = stronger
    # Add noise: 85% of the time the "true" better song wins
    if rank_a < rank_b:
        return song_a.song_id if random.random() < 0.85 else song_b.song_id
    elif rank_b < rank_a:
        return song_b.song_id if random.random() < 0.85 else song_a.song_id
    else:
        # Tie in true ranking - coin flip
        return song_a.song_id if random.random() < 0.5 else song_b.song_id


async def run_simulation(session_id: str, num_additional_duels: int = 30):
    """Run full pairing + ranking simulation."""
    
    # Fetch real session data
    songs_data, comparisons_data = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id)
    )
    
    print(f"\n{'='*70}")
    print("PAIRING-V2 + BRADLEY-TERRY SIMULATION")
    print(f"{'='*70}")
    print(f"Starting with {len(songs_data)} songs, {len(comparisons_data)} comparisons\n")
    
    # Build initial song state
    songs = [
        SimSong(
            song_id=str(s["song_id"]),
            name=s.get("name", "?"),
            bt_strength=s.get("bt_strength") or 0.0,
            local_elo=s.get("local_elo") or 1500.0,
            comparison_count=s.get("comparison_count") or 0
        )
        for s in songs_data
    ]
    id_to_song = {s.song_id: s for s in songs}
    
    # Build comparison history
    history = ComparisonHistory()
    comparisons = []
    for c in comparisons_data:
        a_id = str(c["song_a_id"])
        b_id = str(c["song_b_id"])
        history.compared_pairs.add(make_pair_key(a_id, b_id))
        comparisons.append({
            "song_a_id": a_id,
            "song_b_id": b_id,
            "winner_id": str(c["winner_id"]) if c.get("winner_id") else None,
            "is_tie": c.get("is_tie", False),
            "decision_time_ms": c.get("decision_time_ms")
        })
    
    # Define "true" rankings (friend's stated preferences)
    # Delilah is #1 (undefeated), then songs 11-14 should be top 5
    true_top = ["Delilah", "ten", "adore u", "Victory Lap", "leavemealone"]
    
    # Build true rankings: friend's picks are top 4, rest by current BT score
    song_ids = [s.song_id for s in songs]
    current_bt = RankingManager.compute_bradley_terry(song_ids, comparisons)
    current_ranked = sorted(current_bt.items(), key=lambda x: -x[1])
    
    true_rankings = {}
    rank = 1
    
    # First: friend's top 5
    # Delilah is undefeated (100% win rate)
    undefeated_ids = set()
    for name in true_top:
        for s in songs:
            if name.lower() in s.name.lower() and "Five" not in s.name:
                true_rankings[s.song_id] = rank
                if "delilah" in name.lower():
                    undefeated_ids.add(s.song_id)
                rank += 1
                break
    
    # Then: everyone else by current BT
    for sid, _ in current_ranked:
        if sid not in true_rankings:
            true_rankings[sid] = rank
            rank += 1
    
    print("TRUE RANKINGS (what we're simulating):")
    print("-" * 50)
    for sid, r in sorted(true_rankings.items(), key=lambda x: x[1])[:10]:
        name = id_to_song[sid].name[:40]
        print(f"  #{r}: {name}")
    print()
    
    # Show current state
    print("CURRENT STATE (before simulation):")
    print("-" * 50)
    for i, (sid, theta) in enumerate(current_ranked[:10], 1):
        name = id_to_song[sid].name[:35]
        comps = id_to_song[sid].comparison_count
        print(f"{i:2}. {name:35} θ={theta:+.3f} comps={comps}")
    
    conv = RankingManager.calculate_convergence_v2(comparisons, len(songs), current_bt)
    print(f"\nConvergence: {conv}%")
    
    # Run simulation
    print(f"\n{'='*70}")
    print(f"SIMULATING {num_additional_duels} DUELS using pairing-v2...")
    print("-" * 50)
    
    for duel_num in range(1, num_additional_duels + 1):
        # Get next pair using pairing-v2 algorithm
        phase = get_phase(songs)
        pair = get_next_pair_v2(songs, history)
        
        if pair is None:
            print("No more pairs available!")
            break
        
        song_a, song_b = pair
        
        # Simulate the duel outcome
        winner_id = simulate_duel(song_a, song_b, true_rankings, undefeated_ids)
        
        # Record comparison
        comparisons.append({
            "song_a_id": song_a.song_id,
            "song_b_id": song_b.song_id,
            "winner_id": winner_id,
            "is_tie": False,
            "decision_time_ms": 2000
        })
        history.compared_pairs.add(make_pair_key(song_a.song_id, song_b.song_id))
        
        # Update comparison counts
        id_to_song[song_a.song_id].comparison_count += 1
        id_to_song[song_b.song_id].comparison_count += 1
        
        # Re-run BT every 5 duels
        if duel_num % 5 == 0:
            bt_scores = RankingManager.compute_bradley_terry(song_ids, comparisons)
            for sid, theta in bt_scores.items():
                id_to_song[sid].bt_strength = theta
            
            conv = RankingManager.calculate_convergence_v2(comparisons, len(songs), bt_scores)
            
            # Show progress
            winner_name = id_to_song[winner_id].name[:20]
            loser_id = song_b.song_id if winner_id == song_a.song_id else song_a.song_id
            loser_name = id_to_song[loser_id].name[:20]
            print(f"Duel {duel_num:2}: [{phase:12}] {winner_name} beat {loser_name} | Conv: {conv}%")
    
    # Final ranking
    final_bt = RankingManager.compute_bradley_terry(song_ids, comparisons)
    final_ranked = sorted(final_bt.items(), key=lambda x: -x[1])
    final_conv = RankingManager.calculate_convergence_v2(comparisons, len(songs), final_bt)
    
    print(f"\n{'='*70}")
    print(f"FINAL RANKING (after {num_additional_duels} simulated duels):")
    print("-" * 50)
    
    target_ids = set()
    for name in true_top:
        for s in songs:
            if name.lower() in s.name.lower() and "Five" not in s.name:
                target_ids.add(s.song_id)
    
    for i, (sid, theta) in enumerate(final_ranked[:15], 1):
        name = id_to_song[sid].name[:35]
        comps = id_to_song[sid].comparison_count
        marker = " ⭐" if sid in target_ids else ""
        
        # Show rank change
        old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == sid)
        change = old_rank - i
        change_str = f"(+{change})" if change > 0 else f"({change})" if change < 0 else "(=)"
        
        print(f"{i:2}. {name:33} θ={theta:+.3f} comps={comps:2} {change_str:>6}{marker}")
    
    print(f"\nFinal Convergence: {final_conv}%")
    print(f"Total comparisons: {len(comparisons)}")
    
    # Summary for target songs
    print(f"\n{'='*70}")
    print("TARGET SONGS SUMMARY:")
    print("-" * 50)
    for name in true_top:
        for sid in target_ids:
            if name.lower() in id_to_song[sid].name.lower():
                old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == sid)
                new_rank = next(j for j, (s, _) in enumerate(final_ranked, 1) if s == sid)
                in_top5 = "✓" if new_rank <= 5 else ""
                in_top10 = "✓" if new_rank <= 10 else ""
                print(f"  {id_to_song[sid].name[:30]:30} #{old_rank:2} → #{new_rank:2} | Top5:{in_top5:2} Top10:{in_top10:2}")


async def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "c30f49c7-82ca-419b-956a-95b426ddad23"
    num_duels = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    await run_simulation(session_id, num_duels)


if __name__ == "__main__":
    asyncio.run(main())
