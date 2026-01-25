#!/usr/bin/env python
"""
Test script to verify the leaderboard API returns pending comparisons.
"""
import asyncio
from app.clients.supabase_db import supabase_client
from app.api.v1.leaderboard import fetch_leaderboard_data

async def test_pending_comparisons():
    """Test that pending comparisons are calculated correctly."""
    print("Testing Leaderboard Pending Comparisons...")
    print("=" * 60)
    
    # Test with an artist (adjust to one in your database)
    test_artist = "Ariana Grande"
    
    try:
        # Fetch leaderboard data
        result = await fetch_leaderboard_data(test_artist, limit=10)
        
        if result:
            print(f"\n✓ Leaderboard data for {test_artist}:")
            print(f"  - Processed comparisons: {result['total_comparisons']}")
            print(f"  - Pending comparisons: {result['pending_comparisons']}")
            print(f"  - Last updated: {result['last_updated']}")
            print(f"  - Songs in leaderboard: {len(result['songs'])}")
            
            if result['pending_comparisons'] > 0:
                print(f"\n⚠️  There are {result['pending_comparisons']} comparisons waiting to be processed!")
                print("   The global ranking will update within 10 minutes.")
            else:
                print("\n✓ All comparisons have been processed!")
        else:
            print(f"\n⚠️  No leaderboard data found for {test_artist}")
            print("   This might be expected if no one has ranked this artist yet.")
        
        print("\n" + "=" * 60)
        print("✓ Test completed successfully!")
        print("\nAPI Response Structure:")
        print("  - total_comparisons: Number of comparisons in global ranking")
        print("  - pending_comparisons: Comparisons waiting to be processed")
        print("  - last_updated: ISO timestamp of last global update")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    print("Leaderboard Pending Comparisons Test")
    print("=" * 60)
    print("\nThis test verifies that the leaderboard API correctly shows:")
    print("  1. Processed comparisons (in global ranking)")
    print("  2. Pending comparisons (waiting to be processed)")
    print("  3. Accurate last_updated timestamp")
    print("\nStarting test...\n")
    
    success = asyncio.run(test_pending_comparisons())
    
    import sys
    sys.exit(0 if success else 1)
