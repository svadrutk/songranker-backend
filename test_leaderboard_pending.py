#!/usr/bin/env python
"""
Manual test script to verify the leaderboard API returns pending comparisons.
Run with: uv run python test_leaderboard_pending.py [artist_name]
"""
import asyncio
import sys
from typing import Dict, Any

from app.api.v1.leaderboard import fetch_leaderboard_data


def print_section(title: str, width: int = 60) -> None:
    """Print a section header."""
    print("\n" + "=" * width)
    print(title)
    print("=" * width)


def _print_result_summary(result: Dict[str, Any]) -> None:
    """Print the test result summary."""
    pending = result['pending_comparisons']
    
    print("\n✓ Leaderboard data retrieved:")
    print(f"  - Processed comparisons: {result['total_comparisons']}")
    print(f"  - Pending comparisons:   {pending}")
    print(f"  - Last updated:          {result['last_updated']}")
    print(f"  - Songs in leaderboard:  {len(result['songs'])}")
    
    if pending > 0:
        print(f"\n⚠️  {pending} comparisons waiting to be processed!")
        print("   The global ranking will update within 10 minutes.")
    else:
        print("\n✓ All comparisons have been processed!")


def _print_api_structure_info() -> None:
    """Print API response structure documentation."""
    print_section("API Response Structure")
    print("  - total_comparisons:   Number of comparisons in global ranking")
    print("  - pending_comparisons: Comparisons waiting to be processed")
    print("  - last_updated:        ISO timestamp of last global update")


async def test_pending_comparisons(artist: str) -> bool:
    """
    Test that pending comparisons are calculated correctly.
    
    Args:
        artist: The artist name to test
    
    Returns:
        True if test passed, False otherwise
    """
    print_section(f"Testing Leaderboard for: {artist}")
    
    try:
        result = await fetch_leaderboard_data(artist, limit=10)
        
        if not result:
            print(f"\n⚠️  No leaderboard data found for '{artist}'")
            print("   This might be expected if no one has ranked this artist yet.")
            return False
        
        _print_result_summary(result)
        _print_api_structure_info()
        
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main() -> int:
    """Main entry point."""
    # Get artist from command line or use default
    default_artist = "Ariana Grande"
    artist = sys.argv[1] if len(sys.argv) > 1 else default_artist
    
    print_section("Leaderboard Pending Comparisons Test")
    print("\nThis test verifies that the leaderboard API correctly shows:")
    print("  1. Processed comparisons (in global ranking)")
    print("  2. Pending comparisons (waiting to be processed)")
    print("  3. Accurate last_updated timestamp")
    
    success = asyncio.run(test_pending_comparisons(artist))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
