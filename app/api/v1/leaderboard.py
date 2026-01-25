import asyncio
import logging
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel
from app.clients.supabase_db import supabase_client
from app.core.cache import cache
from app.core.limiter import limiter

logger = logging.getLogger(__name__)

# Global update interval - matches the value in tasks.py
GLOBAL_UPDATE_INTERVAL_MINUTES = 10

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
    total_comparisons: int
    pending_comparisons: int
    last_updated: Optional[str] = None


async def fetch_leaderboard_data(artist: str, limit: int) -> Optional[dict]:
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
    processed_comparisons = stats.get("total_comparisons_count", 0) if stats else 0
    pending_comparisons = max(0, total_comparisons - processed_comparisons)
    
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
    logger.info(f"GET /leaderboard/{artist} (limit={limit})")
    
    # Cache the leaderboard for 2 minutes to handle traffic bursts
    cache_key = f"leaderboard:{artist}:{limit}"
    result = await cache.get_or_fetch(
        cache_key,
        lambda: fetch_leaderboard_data(artist, limit),
        ttl_seconds=120,
        background_tasks=background_tasks
    )
    
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No leaderboard data found for artist: {artist}"
        )
    
    # Trigger global update if needed (pending comparisons + stale data)
    await _maybe_trigger_update_on_view(artist, result, background_tasks)
    
    return result

async def _maybe_trigger_update_on_view(artist: str, result: dict, background_tasks: BackgroundTasks):
    """
    Trigger a global ranking update if:
    1. There are pending comparisons
    2. The ranking hasn't been updated in 10+ minutes
    
    This ensures that leaderboards eventually update even if no one is actively ranking.
    """
    pending = result.get("pending_comparisons", 0)
    last_updated = result.get("last_updated")
    
    # No pending comparisons - nothing to update
    if pending == 0:
        return
    
    # No last_updated timestamp - this shouldn't happen but play it safe
    if not last_updated:
        logger.warning(f"[GLOBAL] Artist '{artist}' has pending comparisons but no last_updated timestamp")
        return
    
    # Check if enough time has passed
    try:
        if isinstance(last_updated, str):
            last_update_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
        else:
            last_update_dt = last_updated
        
        time_since_update = datetime.now(timezone.utc) - last_update_dt
        interval_threshold = timedelta(minutes=GLOBAL_UPDATE_INTERVAL_MINUTES)
        
        if time_since_update >= interval_threshold:
            # Trigger update in background
            from app.core.queue import task_queue
            from app.tasks import run_global_ranking_update
            
            background_tasks.add_task(
                lambda: task_queue.enqueue(run_global_ranking_update, artist)
            )
            logger.info(f"[GLOBAL] Triggered update for '{artist}' on leaderboard view ({pending} pending, {time_since_update.total_seconds():.0f}s since last update)")
        else:
            logger.debug(f"[GLOBAL] Skipping update for '{artist}' - only {time_since_update.total_seconds():.0f}s since last update")
    
    except Exception as e:
        logger.error(f"[GLOBAL] Error checking update trigger for '{artist}': {e}")


@router.get("/leaderboard/{artist}/stats")
@limiter.limit("60/minute")
async def get_artist_leaderboard_stats(request: Request, artist: str):
    """
    Get statistics about an artist's global leaderboard.
    Returns metadata without the full song list (lighter weight than full leaderboard).
    """
    stats, total_comparisons = await asyncio.gather(
        supabase_client.get_artist_stats(artist),
        supabase_client.get_artist_total_comparisons(artist)
    )
    
    if not stats:
        raise HTTPException(
            status_code=404,
            detail=f"No statistics found for artist: {artist}"
        )
    
    # Calculate pending comparisons
    processed_comparisons = stats.get("total_comparisons_count", 0)
    pending_comparisons = max(0, total_comparisons - processed_comparisons)
    
    return {
        "artist": artist,
        "total_comparisons": processed_comparisons,
        "pending_comparisons": pending_comparisons,
        "last_updated": stats.get("last_global_update_at"),
        "created_at": stats.get("created_at")
    }
