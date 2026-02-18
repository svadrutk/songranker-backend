#!/usr/bin/env python
"""
Aggressive simulation: What if under-compared songs beat EVERYONE?
"""
import asyncio
import sys
from copy import deepcopy
from app.clients.supabase_db import supabase_client
from app.core.ranking import RankingManager


async def simulate_aggressive(session_id: str):
    """Simulate adding comparisons where targets beat top songs too."""
    
    # Fetch real data
    songs, comparisons = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id)
    )
    
    print(f"\n{'='*70}")
    print("AGGRESSIVE SIMULATION: What if these songs are THE top 4?")
    print(f"{'='*70}\n")
    
    # Build lookups
    id_to_name = {str(s["song_id"]): s.get("name", "?") for s in songs}
    name_to_id = {s.get("name", "?"): str(s["song_id"]) for s in songs}
    
    # Get current ranking
    song_ids = list(id_to_name.keys())
    current_bt = RankingManager.compute_bradley_terry(song_ids, comparisons)
    current_ranked = sorted(current_bt.items(), key=lambda x: -x[1])
    
    print("CURRENT TOP 10:")
    print("-" * 50)
    for i, (sid, theta) in enumerate(current_ranked[:10], 1):
        name = id_to_name[sid][:40]
        print(f"{i:2}. {name:40} θ={theta:+.3f}")
    
    # Target songs
    target_songs = ["ten", "adore u", "Victory Lap", "leavemealone"]
    target_ids = []
    for target in target_songs:
        for name, sid in name_to_id.items():
            if target.lower() in name.lower() and "Five" not in name:
                target_ids.append(sid)
                break
    
    print("\nTarget songs that will beat everyone:")
    for tid in target_ids:
        print(f"  ⭐ {id_to_name[tid]}")
    
    # Current top 4 that will be "dethroned"
    top4_ids = [sid for sid, _ in current_ranked[:4]]
    print("\nCurrent top 4 that targets will beat:")
    for sid in top4_ids:
        print(f"  - {id_to_name[sid]}")
    
    # Create synthetic comparisons:
    # 1. Each target beats the current top 4
    # 2. Each target beats songs ranked 15-25
    synthetic_comparisons = []
    
    # Targets beat top 4
    for target_id in target_ids:
        for top_id in top4_ids:
            if target_id != top_id:
                synthetic_comparisons.append({
                    "song_a_id": target_id,
                    "song_b_id": top_id,
                    "winner_id": target_id,
                    "is_tie": False,
                    "decision_time_ms": 1500  # Very fast = very confident
                })
    
    # Targets beat mid-tier (15-25)
    mid_tier_ids = [sid for sid, _ in current_ranked[14:25]]
    for target_id in target_ids:
        for mid_id in mid_tier_ids:
            synthetic_comparisons.append({
                "song_a_id": target_id,
                "song_b_id": mid_id,
                "winner_id": target_id,
                "is_tie": False,
                "decision_time_ms": 2000
            })
    
    print(f"\nAdding {len(synthetic_comparisons)} synthetic comparisons...")
    print("  - Each target beats current top 4")
    print("  - Each target beats songs ranked 15-25")
    
    # Combine real + synthetic
    simulated_comparisons = deepcopy(comparisons) + synthetic_comparisons
    
    # Re-run Bradley-Terry
    simulated_bt = RankingManager.compute_bradley_terry(song_ids, simulated_comparisons)
    simulated_ranked = sorted(simulated_bt.items(), key=lambda x: -x[1])
    
    print(f"\n{'='*70}")
    print("SIMULATED TOP 15 (targets beat top 4 + mid-tier):")
    print("-" * 50)
    
    for i, (sid, theta) in enumerate(simulated_ranked[:15], 1):
        name = id_to_name[sid][:40]
        marker = " ⭐ FRIEND'S PICK" if sid in target_ids else ""
        old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == sid)
        change = old_rank - i
        change_str = f"(+{change})" if change > 0 else f"({change})" if change < 0 else "(=)"
        print(f"{i:2}. {name:36} θ={theta:+.3f} {change_str:>6}{marker}")
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Final positions if these are truly the favorites:")
    print("-" * 50)
    for target_id in target_ids:
        name = id_to_name[target_id][:30]
        old_rank = next(j for j, (s, _) in enumerate(current_ranked, 1) if s == target_id)
        new_rank = next(j for j, (s, _) in enumerate(simulated_ranked, 1) if s == target_id)
        in_top = "✓ TOP 5!" if new_rank <= 5 else ""
        print(f"  {name:30} #{old_rank:2} → #{new_rank:2}  ({old_rank - new_rank:+d}) {in_top}")
    
    # Show what happened to the former top 4
    print("\nFormer top 4 after being beaten:")
    for tid in top4_ids:
        name = id_to_name[tid][:30]
        new_rank = next(j for j, (s, _) in enumerate(simulated_ranked, 1) if s == tid)
        print(f"  {name:30} #1-4 → #{new_rank}")


async def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "c30f49c7-82ca-419b-956a-95b426ddad23"
    await simulate_aggressive(session_id)


if __name__ == "__main__":
    asyncio.run(main())
