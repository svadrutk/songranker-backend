import asyncio
import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel
from app.clients.supabase_db import supabase_client
from app.core.cache import cache
from app.core.limiter import limiter
from app.core.global_ranking_config import (
    GLOBAL_UPDATE_INTERVAL_MINUTES,
    REDIS_LOCK_EXPIRY_SECONDS,
    get_global_update_lock_key
)
from app.core.global_ranking_utils import (
    calculate_pending_comparisons,
    should_trigger_global_update,
    get_seconds_since_update
)

logger = logging.getLogger(__name__)

router = APIRouter()


class LeaderboardSong(BaseModel):
    """A song entry in the global leaderboard."""
    id: str
    name: str
    artist: str
    album: Optional[str] = None
    album_art_url: Optional[str] = None
    global_elo: float
    global_bt_strength: float
    global_votes_count: int
    rank: int


class LeaderboardResponse(BaseModel):
    """Response for the global leaderboard."""
    artist: str
    songs: List[LeaderboardSong]
    total_comparisons: int  # Number of comparisons already processed into global Elo
    pending_comparisons: int = 0  # Number of comparisons waiting for next global update
    last_updated: Optional[str] = None


async def fetch_leaderboard_data(artist: str, limit: int) -> Optional[Dict[str, Any]]:
    """Fetch leaderboard and artist stats, then build response as a dict for caching."""
    songs_data, stats, total_comparisons = await asyncio.gather(
        supabase_client.get_leaderboard(artist, limit),
        supabase_client.get_artist_stats(artist),
        supabase_client.get_artist_total_comparisons(artist)
    )
    
    if not songs_data:
        return None
    
    songs = [
        {
            "id": str(s["id"]),
            "name": s["name"],
            "artist": s["artist"],
            "album": s.get("album"),
            "album_art_url": s.get("cover_url"),  # Map cover_url to album_art_url for API response
            "global_elo": s["global_elo"],
            "global_bt_strength": s["global_bt_strength"],
            "global_votes_count": s["global_votes_count"],
            "rank": idx + 1
        }
        for idx, s in enumerate(songs_data)
    ]
    
    # Calculate pending comparisons (total - processed)
    processed_comparisons, pending_comparisons = calculate_pending_comparisons(
        total_comparisons, stats
    )
    
    return {
        "artist": artist,
        "songs": songs,
        "total_comparisons": processed_comparisons,
        "pending_comparisons": pending_comparisons,
        "last_updated": stats.get("last_global_update_at") if stats else None
    }


@router.get("/leaderboard/{artist}", response_model=LeaderboardResponse)
@limiter.limit("60/minute")
async def get_global_leaderboard(
    request: Request,
    background_tasks: BackgroundTasks,
    artist: str,
    limit: int = Query(100, ge=1, le=500, description="Number of songs to return")
):
    """
    Get the global leaderboard for a specific artist.
    Returns the top songs ranked by global_elo across all user sessions.
    
    - **artist**: The artist name (must match exactly as stored in the database)
    - **limit**: Maximum number of songs to return (default: 100, max: 500)
    
    If there are pending comparisons and the ranking hasn't updated in 10+ minutes,
    this endpoint will trigger a background global ranking update.
    """
    logger.info(f"[API] GET /leaderboard/{artist} limit={limit}")
    
    # Cache the leaderboard for 2 minutes (TTL matches README documentation)
    # Lower TTL reduces impact of cross-worker memory cache desync
    # memory_ttl_seconds=5 ensures the API worker checks Redis frequently
    norm_artist = artist.lower()
    cache_key = f"leaderboard:{norm_artist}:{limit}"
    result, metadata = await cache.get_or_fetch(
        cache_key,
        lambda: fetch_leaderboard_data(artist, limit),
        ttl_seconds=120,
        background_tasks=background_tasks,
        return_metadata=True,
        memory_ttl_seconds=5
    )
    
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No leaderboard data found for artist: {artist}"
        )
    
    # Trigger global update if needed (pending comparisons + stale data)
    # Trigger even if metadata says is_stale=True, because the background revalidation
    # of the cache only refreshes the VIEW, it doesn't trigger the WORKER to process votes.
    await _maybe_trigger_update_on_view(artist, result, background_tasks)
    
    return result

async def _try_acquire_update_lock(artist: str) -> bool:
    """
    Try to acquire Redis lock for global update.
    
    Args:
        artist: The artist name
    
    Returns:
        True if lock was acquired, False otherwise
    """
    from app.core.queue import get_async_redis
    
    redis = get_async_redis()
    lock_key = get_global_update_lock_key(artist)
    
    # Try to acquire lock (set if not exists, expire in 5 minutes)
    lock_acquired = await redis.set(lock_key, "1", ex=REDIS_LOCK_EXPIRY_SECONDS, nx=True)
    
    if not lock_acquired:
        logger.debug(f"[GLOBAL] Update already in progress for artist='{artist}' - skipping")
    
    return lock_acquired


def _enqueue_global_update(
    artist: str, 
    background_tasks: BackgroundTasks, 
    result: Dict[str, Any]
) -> None:
    """
    Enqueue global ranking update task.
    
    Args:
        artist: The artist name
        background_tasks: FastAPI background tasks
        result: Leaderboard result dict containing pending comparisons and last_updated
    """
    from app.core.queue import leaderboard_queue
    from app.tasks import run_global_ranking_update
    
    pending = result.get("pending_comparisons", 0)
    last_updated = result.get("last_updated")
    
    # Enqueue the task using background_tasks.add_task with proper function reference
    background_tasks.add_task(
        leaderboard_queue.enqueue,
        run_global_ranking_update,
        artist
    )
    
    # Log with time since last update if available
    if last_updated:
        time_since = get_seconds_since_update(last_updated)
        logger.info(
            f"[GLOBAL] Triggered update for artist='{artist}' on leaderboard view "
            f"(pending={pending}, time_since_last={time_since:.0f}s)"
        )
    else:
        logger.info(
            f"[GLOBAL] Triggered update for artist='{artist}' on leaderboard view "
            f"(pending={pending})"
        )


async def _maybe_trigger_update_on_view(
    artist: str, 
    result: Dict[str, Any], 
    background_tasks: BackgroundTasks
) -> None:
    """
    Trigger a global ranking update if:
    1. There are pending comparisons
    2. The ranking hasn't been updated in 10+ minutes
    3. No update is currently in progress (checked via Redis lock)
    
    This ensures that leaderboards eventually update even if no one is actively ranking.
    
    Args:
        artist: The artist name
        result: Leaderboard result dict
        background_tasks: FastAPI background tasks
    """
    try:
        # Check if update should be triggered based on pending comparisons and staleness
        if not await should_trigger_global_update(
            artist,
            result.get("last_updated"),
            result.get("pending_comparisons", 0)
        ):
            return
        
        # Try to acquire lock and enqueue update if successful
        if await _try_acquire_update_lock(artist):
            _enqueue_global_update(artist, background_tasks, result)
    
    except ValueError as e:
        logger.warning(f"[GLOBAL] Invalid data for artist='{artist}': {e}")
    except ConnectionError as e:
        logger.error(f"[GLOBAL] Redis connection failed for artist='{artist}': {e}")
    except Exception as e:
        logger.error(
            f"[GLOBAL] Unexpected error checking update trigger for artist='{artist}': {e}",
            exc_info=True
        )


@router.get("/leaderboard/{artist}/stats")
@limiter.limit("60/minute")
async def get_artist_leaderboard_stats(request: Request, artist: str) -> Dict[str, Any]:
    """
    Get statistics about an artist's global leaderboard.
    Returns metadata without the full song list (lighter weight than full leaderboard).
    """
    async def fetch_stats():
        stats, total_comparisons = await asyncio.gather(
            supabase_client.get_artist_stats(artist),
            supabase_client.get_artist_total_comparisons(artist)
        )
        
        if not stats:
            return None
        
        # Calculate pending comparisons
        processed_comparisons, pending_comparisons = calculate_pending_comparisons(
            total_comparisons, stats
        )
        
        return {
            "artist": artist,
            "total_comparisons": processed_comparisons,
            "pending_comparisons": pending_comparisons,
            "last_updated": stats.get("last_global_update_at"),
            "created_at": stats.get("created_at")
        }
    
    result = await cache.get_or_fetch(
        f"leaderboard_stats:{artist.lower()}",
        fetch_stats,
        ttl_seconds=60,
        memory_ttl_seconds=5
    )
    
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No statistics found for artist: {artist}"
        )
    
    return result
