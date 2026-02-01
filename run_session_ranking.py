#!/usr/bin/env python
"""
Debug script to re-run ranking for a specific session through the new algorithm.
Usage: python run_session_ranking.py <session_id>
"""
import asyncio
import sys
import logging
from app.tasks import process_ranking_update
from app.clients.supabase_db import supabase_client
from app.core.ranking import RankingManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def debug_session_ranking(session_id: str):
    """
    Run the new ranking algorithm on a session and print detailed results.
    """
    print(f"\n{'='*60}")
    print(f"Re-running ranking for session: {session_id}")
    print(f"{'='*60}\n")
    
    # 1. Fetch session data
    songs, comparisons = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id)
    )
    
    print(f"Found {len(songs)} songs and {len(comparisons)} comparisons\n")
    
    if not songs:
        print("ERROR: No songs found for this session!")
        return
    
    # 2. Show current state (before update)
    print("CURRENT STATE (before re-ranking):")
    print("-" * 50)
    sorted_songs = sorted(songs, key=lambda s: s.get("bt_strength") or 0, reverse=True)
    for i, s in enumerate(sorted_songs[:15], 1):
        name = s.get("name", "?")[:35]
        bt = s.get("bt_strength") or 0
        elo = s.get("local_elo") or 1500
        print(f"{i:2}. {name:35} θ={bt:+.3f} Elo={elo:.0f}")
    print()
    
    # 3. Run the new algorithm
    song_ids = [str(s["song_id"]) for s in songs]
    bt_scores = RankingManager.compute_bradley_terry(song_ids, comparisons)
    
    print("NEW RANKING (after Bradley-Terry via choix):")
    print("-" * 50)
    
    # Sort by new BT strength
    ranked = sorted(bt_scores.items(), key=lambda x: -x[1])
    
    # Create lookup for song names
    id_to_name = {str(s["song_id"]): s.get("name", "?") for s in songs}
    
    for i, (sid, theta) in enumerate(ranked[:20], 1):
        name = id_to_name.get(sid, "?")[:35]
        elo = RankingManager.theta_to_elo(theta)
        print(f"{i:2}. {name:35} θ={theta:+.3f} Elo={elo:.0f}")
    
    if len(ranked) > 20:
        print(f"    ... ({len(ranked) - 20} more songs)")
    
    # 4. Calculate new convergence
    convergence = RankingManager.calculate_convergence_v2(comparisons, len(songs), bt_scores)
    coverage = RankingManager.calculate_coverage(comparisons, len(songs))
    separation = RankingManager.calculate_separation(bt_scores, comparisons)
    
    print(f"\nMETRICS:")
    print("-" * 50)
    print(f"Coverage:     {coverage:.2%}")
    print(f"Separation:   {separation:.2%}")
    print(f"Convergence:  {convergence}%")
    
    # 5. Ask if user wants to persist
    print(f"\n{'='*60}")
    response = input("Persist these changes to the database? [y/N]: ").strip().lower()
    
    if response == 'y':
        print("\nPersisting changes...")
        await process_ranking_update(session_id)
        print("Done! Session has been re-ranked.")
    else:
        print("\nNo changes made.")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python run_session_ranking.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    await debug_session_ranking(session_id)


if __name__ == "__main__":
    asyncio.run(main())
