import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel
from app.clients.supabase_db import supabase_client
from app.core.cache import cache
from app.core.limiter import limiter

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
    total_comparisons: int
    last_updated: Optional[str] = None


async def fetch_leaderboard_data(artist: str, limit: int) -> Optional[dict]:
    """Fetch leaderboard and artist stats, then build response as a dict for caching."""
    songs_data, stats = await asyncio.gather(
        supabase_client.get_leaderboard(artist, limit),
        supabase_client.get_artist_stats(artist)
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
    
    return {
        "artist": artist,
        "songs": songs,
        "total_comparisons": stats.get("total_comparisons_count", 0) if stats else 0,
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
    
    return result


@router.get("/leaderboard/{artist}/stats")
@limiter.limit("60/minute")
async def get_artist_leaderboard_stats(request: Request, artist: str):
    """
    Get statistics about an artist's global leaderboard.
    Returns metadata without the full song list (lighter weight than full leaderboard).
    """
    stats = await supabase_client.get_artist_stats(artist)
    
    if not stats:
        raise HTTPException(
            status_code=404,
            detail=f"No statistics found for artist: {artist}"
        )
    
    return {
        "artist": artist,
        "total_comparisons": stats.get("total_comparisons_count", 0),
        "last_updated": stats.get("last_global_update_at"),
        "created_at": stats.get("created_at")
    }
