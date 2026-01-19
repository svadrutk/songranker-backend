import logging
from typing import List
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.schemas.session import SessionCreate, SessionResponse
from app.clients.supabase_db import supabase_client
from app.core.utils import normalize_title
from app.core.deduplication import deep_deduplicate_session

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/sessions", response_model=SessionResponse)
async def create_session(session_data: SessionCreate, background_tasks: BackgroundTasks):
    """
    Initialize a ranking session.
    1. Normalizes song titles.
    2. Resolves songs in the global catalog.
    3. Links songs to the new session.
    4. Triggers background deep deduplication.
    """
    try:
        # 1. Normalize and prepare songs for upsert
        prepared_songs = [
            {
                "name": s.name,
                "artist": s.artist,
                "album": s.album,
                "normalized_name": normalize_title(s.name),
                "spotify_id": s.spotify_id
            }
            for s in session_data.songs
        ]

        if not prepared_songs:
            raise HTTPException(status_code=400, detail="No songs provided")

        # 2. Bulk upsert songs to global catalog
        # This ensures we have IDs for all songs, reusing existing ones if they match (artist, normalized_name)
        resolved_songs = await supabase_client.bulk_upsert_songs(prepared_songs)
        song_ids = [s["id"] for s in resolved_songs]

        # 3. Create the session
        session_id = await supabase_client.create_session(
            user_id=str(session_data.user_id) if session_data.user_id else None
        )

        # 4. Link songs to session
        await supabase_client.link_session_songs(session_id, song_ids)

        # 5. Trigger deep deduplication in the background
        background_tasks.add_task(deep_deduplicate_session, session_id)

        from uuid import UUID
        return SessionResponse(
            session_id=UUID(session_id),
            count=len(song_ids)
        )

    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
