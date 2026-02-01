#!/usr/bin/env python
"""
Simulate what happens if under-compared songs get more matchups
and win (assuming they're actually top 5 material).
"""
import asyncio
import sys
from copy import deepcopy
from app.clients.supabase_db import supabase_client
from app.core.ranking import RankingManager


async def simulate_top5(session_id: str):
    """Simulate adding comparisons for under-compared top candidates."""
    
    # Fetch real data
    songs, comparisons = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id)
    )
    
    print(f"\n{'='*70}")
    print("SIMULATION: What if under-compared songs are actually top 5?")
    print(f"{'='*70}\n")
    
    # Build lookups
    id_to_name = {str(s["song_id"]): s.get("name", "?") for s in songs}
    name_to_id = {s.get("name", "?"): str(s["song_id"]) for s in songs}
    
    # Get current ranking
    song_ids = list(id_to_name.keys())
    current_bt = RankingManager.compute_bradley_terry(song_ids, comparisons)
    current_ranked = sorted(current_bt.items(), key=lambda x: -x[1])
    
    print("CURRENT TOP 15:")
    print("-" * 50)
    for i, (sid, theta) in enumerate(current_ranked[:15], 1):
        name = id_to_name[sid][:40]
        print(f"{i:2}. {name:40} θ={theta:+.3f}")
    
    # Target songs we want to test (the ones user's friend says should be top 5)
    target_songs = ["ten", "adore u", "Victory Lap", "leavemealone"]
    target_ids = []
    for target in target_songs:
        for name, sid in name_to_id.items():
            if target.lower() in name.lower() and "Five" not in name:  # Exclude "Victory Lap Five"
                target_ids.append(sid)
                print(f"\nTarget: {name} (id: {sid[:8]}...)")
                break
    
    # Find "fodder" songs - songs ranked 20+ that we'll have targets beat
    fodder_ids = [sid for sid, _ in current_ranked[20:30]]
    
    print(f"\nFodder songs (ranked 20-30) that targets will beat:")
    for sid in fodder_ids:
        print(f"  - {id_to_name[sid][:40]}")
    
    # Create synthetic comparisons
    # Each target song beats each fodder song once
    synthetic_comparisons = []
    for target_id in target_ids:
        for fodder_id in fodder_ids:
            synthetic_comparisons.append({
                "song_a_id": target_id,
                "song_b_id": fodder_id,
                "winner_id": target_id,
                "is_tie": False,
                "decision_time_ms": 2000  # Fast decision = high confidence
            })
    
    print(f"\nAdding {len(synthetic_comparisons)} synthetic comparisons...")
    print(f"(Each target beats 10 fodder songs)\n")
    
    # Combine real + synthetic
    simulated_comparisons = deepcopy(comparisons) + synthetic_comparisons
    
    # Re-run Bradley-Terry
    simulated_bt = RankingManager.compute_bradley_terry(song_ids, simulated_comparisons)
    simulated_ranked = sorted(simulated_bt.items(), key=lambda x: -x[1])
    
    print("=" * 70)
    print("SIMULATED TOP 15 (after adding wins for under-compared songs):")
    print("-" * 50)
    
    for i, (sid, theta) in enumerate(simulated_ranked[:15], 1):
        name = id_to_name[sid][:40]
        # Mark if this is a target song
        marker = " ⭐" if sid in target_ids else ""
        # Show rank change
        old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == sid)
        change = old_rank - i
        change_str = f"(+{change})" if change > 0 else f"({change})" if change < 0 else "(=)"
        print(f"{i:2}. {name:38} θ={theta:+.3f} {change_str:>6}{marker}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Where did target songs end up?")
    print("-" * 50)
    for target_id in target_ids:
        name = id_to_name[target_id][:30]
        old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == target_id)
        new_rank = next(j for j, (s, _) in enumerate(simulated_ranked, 1) if s == target_id)
        print(f"  {name:30} #{old_rank:2} → #{new_rank:2}  ({old_rank - new_rank:+d} positions)")
    
    # Calculate new convergence
    new_conv = RankingManager.calculate_convergence_v2(simulated_comparisons, len(songs), simulated_bt)
    old_conv = RankingManager.calculate_convergence_v2(comparisons, len(songs), current_bt)
    print(f"\nConvergence: {old_conv}% → {new_conv}%")


async def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "c30f49c7-82ca-419b-956a-95b426ddad23"
    await simulate_top5(session_id)


if __name__ == "__main__":
    asyncio.run(main())
