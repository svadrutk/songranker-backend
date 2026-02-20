import asyncio
import logging
import re
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, UUID4

from app.clients.apple_music import apple_music_client
from app.clients.spotify import spotify_client
from app.core.config import settings
from app.core.track_selection import dedupe_tracks_for_selection, select_anchor_variance_quick_rank
from app.schemas.session import SessionCreate, SessionResponse, SongInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["imports"])


class PlaylistImportRequest(BaseModel):
    url: str
    user_id: Optional[UUID4] = None
    limit: Optional[int] = None
    rank_mode: Optional[str] = "quick_rank"  # quick_rank | rank_all


# ---------------------------------------------------------------------------
# URL parsers
# ---------------------------------------------------------------------------

def extract_spotify_playlist_id(url: str) -> Optional[str]:
    """Extract playlist ID from a Spotify URL (open.spotify.com only)."""
    # Must be a Spotify domain to avoid false matches on Apple Music URLs
    if "spotify.com" not in url.lower():
        return None
    match = re.search(r"playlist/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def extract_apple_music_playlist_info(url: str) -> tuple[Optional[str], str]:
    """Extract (playlist_id, storefront) from a public Apple Music playlist URL.

    Handles:
      https://music.apple.com/us/playlist/my-playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde
      https://music.apple.com/us/playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde  (no slug)

    Returns (playlist_id, storefront), or (None, "us") if no match.
    """
    # pl. IDs are hex characters after the dot
    pattern = r"music\.apple\.com/([a-z]{2})/playlist/(?:[^/]+/)?(pl\.[a-f0-9]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(2), match.group(1)
    return None, "us"


# ---------------------------------------------------------------------------
# Import endpoint
# ---------------------------------------------------------------------------

@router.post("/playlist", response_model=SessionResponse)
async def import_playlist(
    request: Request,
    import_data: PlaylistImportRequest,
    background_tasks: BackgroundTasks,
):
    """Import a public Spotify or Apple Music playlist and create a ranking session."""
    http_client = request.app.state.http_client

    rank_mode = (import_data.rank_mode or "quick_rank").strip().lower()
    if rank_mode not in ("quick_rank", "rank_all"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_RANK_MODE", "message": "rank_mode must be 'quick_rank' or 'rank_all'"},
        )

    # ------------------------------------------------------------------
    # 1. Detect platform and extract IDs
    # ------------------------------------------------------------------
    url_lower = import_data.url.lower()

    if "music.apple.com" in url_lower:
        platform = "apple_music"
        playlist_id, storefront = extract_apple_music_playlist_info(import_data.url)
        if not playlist_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_APPLE_MUSIC_URL",
                    "message": "Could not extract a valid Apple Music playlist ID from the URL. Ensure it is a public playlist link.",
                },
            )
        if not settings.apple_music_configured:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "APPLE_MUSIC_NOT_CONFIGURED",
                    "message": "Apple Music integration is not configured on this server.",
                },
            )
    else:
        platform = "spotify"
        storefront = None
        playlist_id = extract_spotify_playlist_id(import_data.url)
        if not playlist_id:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_SPOTIFY_URL", "message": "Could not extract a valid Spotify playlist ID from the URL."},
            )

    # ------------------------------------------------------------------
    # 2. Fetch metadata and tracks in parallel
    # ------------------------------------------------------------------
    try:
        if platform == "apple_music":
            assert storefront is not None
            fetch_limit = min(int(import_data.limit or 250), 250)
            metadata, raw_tracks = await asyncio.gather(
                apple_music_client.get_playlist_metadata(playlist_id, storefront),
                apple_music_client.get_playlist_tracks(playlist_id, storefront, limit=fetch_limit),
            )
        else:
            fetch_limit = min(int(import_data.limit or 250), 250)
            metadata, raw_tracks = await asyncio.gather(
                spotify_client.get_playlist_metadata(playlist_id, client=http_client),
                spotify_client.get_playlist_tracks(playlist_id, limit=fetch_limit, client=http_client),
            )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response else 500
        if status in (403, 404):
            raise HTTPException(
                status_code=404,
                detail={"code": "PLAYLIST_NOT_FOUND_OR_PRIVATE", "message": "Playlist not found or is private."},
            )
        raise HTTPException(
            status_code=502,
            detail={"code": "UPSTREAM_API_ERROR", "message": f"Error fetching playlist from {platform}."},
        )

    # ------------------------------------------------------------------
    # 3. Map raw tracks to SongInput
    # ------------------------------------------------------------------
    raw_songs = [
        SongInput(
            name=t["name"],
            artist=t["artist"],
            album=t.get("album"),
            spotify_id=t.get("spotify_id"),
            apple_music_id=t.get("apple_music_id"),
            isrc=t.get("isrc"),
            genres=t.get("genres", []),
            cover_url=t.get("cover_url"),
        )
        for t in raw_tracks
        if t.get("name") and t.get("artist")
    ]

    # ------------------------------------------------------------------
    # 4. Deduplicate (always, for both quick_rank and rank_all)
    # ------------------------------------------------------------------
    # Convert to dicts for dedupe_tracks_for_selection which expects dicts
    raw_dicts = [s.model_dump() for s in raw_songs]
    deduped_dicts = dedupe_tracks_for_selection(raw_dicts)

    if not deduped_dicts:
        raise HTTPException(
            status_code=404,
            detail={"code": "PLAYLIST_NO_RANKABLE_TRACKS", "message": "No rankable tracks found in playlist."},
        )

    # ------------------------------------------------------------------
    # 5. Select tracks per rank_mode
    # ------------------------------------------------------------------
    if rank_mode == "quick_rank":
        selected_dicts = select_anchor_variance_quick_rank(
            deduped_dicts, anchors=30, wildcards=20, seed=playlist_id
        )
        quick_rank_strategy = "anchor_variance_30_20"
    else:
        selected_dicts = deduped_dicts[:250]
        quick_rank_strategy = None

    songs = [SongInput(**d) for d in selected_dicts]

    # ------------------------------------------------------------------
    # 6. Build session
    # ------------------------------------------------------------------
    collection_metadata: dict = {
        "owner": metadata.get("owner") or metadata.get("curator"),
        "image_url": metadata.get("image_url"),
        "rank_mode": rank_mode,
        "quick_rank_strategy": quick_rank_strategy,
    }
    if platform == "apple_music" and storefront:
        collection_metadata["storefront"] = storefront

    session_create = SessionCreate(
        user_id=import_data.user_id,
        playlist_id=playlist_id,
        playlist_name=metadata.get("name"),
        source_platform=platform,
        collection_metadata=collection_metadata,
        songs=songs,
    )

    try:
        from app.api.v1.sessions import create_session as internal_create_session
        return await internal_create_session(request, session_create, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create session for playlist {playlist_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail={"code": "IMPORT_FAILED", "message": "Import failed."},
        )
