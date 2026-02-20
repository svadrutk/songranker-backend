from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel, UUID4
from typing import Optional
from app.clients.spotify import spotify_client
from app.schemas.session import SessionCreate, SongInput, SessionResponse
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])

class PlaylistImportRequest(BaseModel):
    url: str
    user_id: Optional[UUID4] = None
    limit: Optional[int] = None

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
        
        # Decide limit: default to Top 40, but if explicit or Rank All toggle logic needed
        # For now, if no limit provided, use the 40-song default from the plan
        request_limit = import_data.limit or 40
        tracks = await spotify_client.get_playlist_tracks(playlist_id, limit=request_limit)
        
        if not tracks:
            raise HTTPException(status_code=404, detail="No rankable tracks found in playlist")
        
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
                "image_url": metadata["image_url"]
            },
            songs=songs
        )
        
        # 4. Call existing create_session logic (via the router function for consistency)
        from app.api.v1.sessions import create_session as internal_create_session
        return await internal_create_session(request, session_create, background_tasks)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import playlist {playlist_id}: {e}")
        if "404" in str(e):
            raise HTTPException(status_code=404, detail="Playlist not found or is private")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
