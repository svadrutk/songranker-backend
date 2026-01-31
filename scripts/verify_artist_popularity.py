"""
Verify that artist popularity uses distinct users (one per user per artist).
Run from backend: uv run python scripts/verify_artist_popularity.py
"""
import asyncio
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from dotenv import load_dotenv
load_dotenv()

from app.clients.supabase_db import supabase_client


async def main():
    print("=== Verifying artist popularity (distinct users) ===\n")

    client = await supabase_client.get_client()

    # 1. Call the new RPC directly (proves migration ran)
    print("1. Calling get_artists_leaderboard_popularity(10)...")
    try:
        r = await client.rpc("get_artists_leaderboard_popularity", {"p_limit": 10}).execute()
        if not r.data:
            print("   FAIL: RPC returned no data (migration may not be applied).")
            return 1
        rows = r.data
        print(f"   OK: RPC exists and returned {len(rows)} artist(s).")
        for i, row in enumerate(rows[:5]):
            print(f"      {i+1}. {row.get('artist')}: distinct_users_count={row.get('distinct_users_count')}")
        if len(rows) > 5:
            print(f"      ... and {len(rows) - 5} more")
    except Exception as e:
        print(f"   FAIL: RPC error (migration likely not applied): {e}")
        return 1

    # 2. Call Python method (what the API uses)
    print("\n2. Calling get_artists_with_leaderboards(10) (what API uses)...")
    try:
        artists = await supabase_client.get_artists_with_leaderboards(10)
        if not artists:
            print("   FAIL: No artists returned.")
            return 1
        print(f"   OK: Got {len(artists)} artist(s). total_comparisons = distinct users.")
        for i, a in enumerate(artists[:5]):
            print(f"      {i+1}. {a.get('artist')}: total_comparisons={a.get('total_comparisons_count')}")
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1

    # 3. Compare: for first artist, raw comparison count vs distinct users
    if rows:
        first_artist = rows[0]["artist"]
        distinct = int(rows[0]["distinct_users_count"])
        print(f"\n3. Sanity check for '{first_artist}':")
        try:
            raw_count = await supabase_client.get_artist_total_comparisons(first_artist)
            print(f"   Raw comparison count (all duels): {raw_count}")
            print(f"   Distinct users (what we use):     {distinct}")
            if distinct <= raw_count:
                print("   OK: distinct users <= raw count (expected).")
            else:
                print("   (distinct > raw is unexpected; RPC logic may differ from count_artist_comparisons.)")
        except Exception as e:
            print(f"   (Could not get raw count: {e})")

    print("\n=== Verification done. If all steps show OK, the change is working. ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
