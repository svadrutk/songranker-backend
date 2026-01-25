#!/usr/bin/env python
"""
Test script to verify the Spotify worker rate limiting setup.
This simulates multiple API calls being routed through the worker.
"""
import asyncio
import sys
from app.clients.spotify import spotify_client
from app.core.queue import spotify_queue

async def test_worker_proxy():
    """Test that the worker proxy method works correctly."""
    print("Testing Spotify Worker Proxy...")
    print("=" * 60)
    
    try:
        # Test 1: Search for an artist
        print("\n1. Testing search_artist_albums via worker...")
        result = await spotify_client.call_via_worker(
            "search_artist_albums",
            artist_name="Taylor Swift",
            timeout=30.0
        )
        print(f"   ✓ Received {len(result)} albums")
        if result:
            print(f"   First album: {result[0]['title']}")
        
        # Test 2: Get album tracks
        if result:
            print("\n2. Testing get_album_tracks via worker...")
            album_id = result[0]['id']
            tracks = await spotify_client.call_via_worker(
                "get_album_tracks",
                spotify_id=album_id,
                timeout=30.0
            )
            print(f"   ✓ Received {len(tracks)} tracks")
            if tracks:
                print(f"   First track: {tracks[0]}")
        
        print("\n" + "=" * 60)
        print("✓ All tests passed! Worker proxy is functioning correctly.")
        print("\nKey points:")
        print("  - All Spotify API calls are now serialized through 1 worker")
        print("  - This prevents rate limiting across multiple Gunicorn instances")
        print("  - The worker uses tenacity for automatic retries on 429 errors")
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        print("\nMake sure:")
        print("  1. Redis is running")
        print("  2. Spotify worker is running: python worker.py --queues spotify")
        print("  3. SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are set in .env")
        return False

def check_queue_status():
    """Check the status of the Spotify queue."""
    print("\nQueue Status:")
    print(f"  - Jobs in spotify queue: {len(spotify_queue)}")
    print(f"  - Failed jobs: {len(spotify_queue.failed_job_registry)}")

if __name__ == "__main__":
    print("Spotify Worker Rate Limiting Test")
    print("=" * 60)
    print("\nPrerequisites:")
    print("  1. Start Redis: redis-server")
    print("  2. Start Spotify Worker: python worker.py --queues spotify")
    print("  3. Set Spotify credentials in .env file")
    print("\nStarting test in 3 seconds...")
    print("(Press Ctrl+C to cancel)")
    
    try:
        import time
        time.sleep(3)
    except KeyboardInterrupt:
        print("\nTest cancelled.")
        sys.exit(0)
    
    check_queue_status()
    success = asyncio.run(test_worker_proxy())
    check_queue_status()
    
    sys.exit(0 if success else 1)
