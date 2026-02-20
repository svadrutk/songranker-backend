from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, UUID4
from typing import Optional
from app.clients.spotify import spotify_client
from app.schemas.session import SessionCreate, SongInput, SessionResponse
from app.core.track_selection import select_anchor_variance_quick_rank
import re
import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])

class PlaylistImportRequest(BaseModel):
    url: str
    user_id: Optional[UUID4] = None
    limit: Optional[int] = None
    rank_mode: Optional[str] = "quick_rank"  # quick_rank | rank_all

def extract_spotify_playlist_id(url: str) -> Optional[str]:
    """Extract playlist ID from a Spotify URL."""
    # Pattern: https://open.spotify.com/playlist/76aXSma1pw1efuiOE9cv6R?si=...
    match = re.search(r"playlist/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None

@router.post("/playlist", response_model=SessionResponse)
async def import_playlist(
    request: Request,
    import_data: PlaylistImportRequest,
    background_tasks: BackgroundTasks
):
    """Import a public Spotify playlist and create a ranking session."""
    playlist_id = extract_spotify_playlist_id(import_data.url)
    if not playlist_id:
        raise HTTPException(status_code=400, detail="Invalid Spotify playlist URL")
    
    try:
        # 1. Fetch metadata and tracks
        metadata = await spotify_client.get_playlist_metadata(playlist_id)

        rank_mode = (import_data.rank_mode or "quick_rank").strip().lower()
        if rank_mode not in ("quick_rank", "rank_all"):
            raise HTTPException(status_code=400, detail={
                "code": "INVALID_RANK_MODE",
                "message": "rank_mode must be 'quick_rank' or 'rank_all'"
            })

        if rank_mode == "rank_all":
            request_limit = min(int(import_data.limit or 250), 250)
            tracks = await spotify_client.get_playlist_tracks(playlist_id, limit=request_limit)
        else:
            # Quick rank: fetch a larger pool for anchor/variance selection.
            pool = await spotify_client.get_playlist_tracks(playlist_id, limit=250)
            tracks = select_anchor_variance_quick_rank(pool, anchors=30, wildcards=20, seed=playlist_id)
        
        if not tracks:
            raise HTTPException(status_code=404, detail={
                "code": "SPOTIFY_PLAYLIST_NO_RANKABLE_TRACKS",
                "message": "No rankable tracks found in playlist"
            })
        
        # 2. Map to SongInput
        songs = [
            SongInput(
                name=t["name"],
                artist=t["artist"],
                spotify_id=t["spotify_id"],
                isrc=t["isrc"],
                genres=t.get("genres", []),
                cover_url=t["cover_url"]
            )
            for t in tracks
        ]
        
        # 3. Create session data
        session_create = SessionCreate(
            user_id=import_data.user_id,
            playlist_id=playlist_id,
            playlist_name=metadata["name"],
            source_platform="spotify",
            collection_metadata={
                "owner": metadata["owner"],
                "image_url": metadata["image_url"],
                "rank_mode": rank_mode,
                "quick_rank_strategy": "anchor_variance_30_20" if rank_mode == "quick_rank" else None,
            },
            songs=songs
        )
        
        # 4. Call existing create_session logic (via the router function for consistency)
        from app.api.v1.sessions import create_session as internal_create_session
        return await internal_create_session(request, session_create, background_tasks)
        
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response else 500
        if status == 404:
            raise HTTPException(status_code=404, detail={
                "code": "SPOTIFY_PLAYLIST_NOT_FOUND_OR_PRIVATE",
                "message": "Playlist not found or is private"
            })
        raise HTTPException(status_code=502, detail={
            "code": "SPOTIFY_API_ERROR",
            "message": "Spotify API request failed",
            "status": status
        })
    except Exception as e:
        logger.error(f"Failed to import playlist {playlist_id}: {e}")
        raise HTTPException(status_code=500, detail={
            "code": "IMPORT_FAILED",
            "message": "Import failed"
        })
