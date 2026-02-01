import logging
import asyncio
from typing import List, Any, Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from app.schemas.session import SessionCreate, SessionResponse, SessionSong, ComparisonCreate, ComparisonResponse, SessionSummary, SessionDetail, UndoComparisonResponse, ComparisonPair
from app.clients.supabase_db import supabase_client
from app.core.utils import normalize_title, calculate_elo
from app.core.queue import task_queue
from app.tasks import run_deep_deduplication
from app.core.limiter import limiter
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/activity/global", response_model=Dict[str, Any])
async def get_global_activity():
    """Return global aggregate stats: total sessions, comparisons, artists ranked, avg convergence."""
    try:
        return await supabase_client.get_global_activity_stats()
    except Exception as e:
        logger.error(f"Failed to fetch global activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/sessions", response_model=List[SessionSummary])
async def get_user_sessions(user_id: UUID):
    """Retrieve all sessions for a specific user with summaries."""
    try:
        summaries = await supabase_client.get_user_sessions(str(user_id))
        return [SessionSummary(**s) for s in summaries]
    except Exception as e:
        logger.error(f"Failed to fetch sessions for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session_detail(session_id: UUID):
    """Retrieve session metadata, songs, comparison count, and comparison history."""
    try:
        songs, count, details, comparison_pairs = await asyncio.gather(
            supabase_client.get_session_songs(str(session_id)),
            supabase_client.get_session_comparison_count(str(session_id)),
            supabase_client.get_session_details(str(session_id)),
            supabase_client.get_session_comparison_pairs(str(session_id))
        )
        return SessionDetail(
            session_id=session_id,
            songs=[SessionSong(**s) for s in songs],
            comparison_count=count,
            convergence_score=details.get("convergence_score"),
            comparisons=[ComparisonPair(**c) for c in comparison_pairs]
        )
    except Exception as e:
        logger.error(f"Failed to fetch detail for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions/{session_id}/songs", response_model=List[SessionSong])
async def get_session_songs(session_id: UUID):
    """Retrieve all songs for a session with their current ratings."""
    try:
        songs = await supabase_client.get_session_songs(str(session_id))
        return [SessionSong(**s) for s in songs]
    except Exception as e:
        logger.error(f"Failed to fetch songs for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: UUID):
    """Delete a session and all its associated data."""
    try:
        # 1. Get primary artist before deletion so we can refresh their global stats
        artist = await supabase_client.get_session_primary_artist(str(session_id))

        # 2. Delete the session (cascades to songs and comparisons)
        await supabase_client.delete_session(str(session_id))

        # 3. Trigger immediate global ranking update to remove these votes from the leaderboard
        if artist:
            from app.tasks import run_global_ranking_update
            from app.core.queue import leaderboard_queue
            leaderboard_queue.enqueue(run_global_ranking_update, artist)
            logger.info(f"Triggered global ranking update for {artist} after session deletion")

        return {"status": "success", "message": "Session deleted"}
    except Exception as e:
        logger.error(f"Failed to delete session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sessions/{session_id}/comparisons", response_model=ComparisonResponse)
async def create_comparison(session_id: UUID, comparison: ComparisonCreate, background_tasks: BackgroundTasks):
    """
    Record a duel result and update local Elo ratings.
    """
    try:
        # 1. Fetch only the relevant songs
        id_a, id_b = str(comparison.song_a_id), str(comparison.song_b_id)
        song_elos = await supabase_client.get_session_song_elos(str(session_id), [id_a, id_b])
        
        elo_map = {str(s["song_id"]): s["local_elo"] for s in song_elos}
        if id_a not in elo_map or id_b not in elo_map:
            raise HTTPException(status_code=404, detail="One or both songs not found in session")

        # 2. Calculate new Elos
        elo_a, elo_b = elo_map[id_a], elo_map[id_b]
        
        if not comparison.winner_id and not comparison.is_tie:
            # Double loss: Penalize both songs (as if each lost to the other)
            # new_elo_a comes from A losing to B
            # new_elo_b comes from B losing to A (which implies A winning against B)
            new_elo_a = calculate_elo(elo_a, elo_b, 0.0)[0]
            new_elo_b = calculate_elo(elo_a, elo_b, 1.0)[1]
        else:
            score_a = 0.5 if comparison.is_tie else (1.0 if str(comparison.winner_id) == id_a else 0.0)
            new_elo_a, new_elo_b = calculate_elo(elo_a, elo_b, score_a)

        # 3. Persist comparison and updated Elos in one atomic operation
        # Pass previous ELO values to support undo functionality
        await supabase_client.record_comparison_and_update_elo(
            str(session_id), id_a, id_b, 
            str(comparison.winner_id) if comparison.winner_id else None,
            comparison.is_tie,
            new_elo_a,
            new_elo_b,
            prev_elo_a=elo_a,
            prev_elo_b=elo_b,
            decision_time_ms=comparison.decision_time_ms
        )

        # 4. Trigger Ranking Update (every 5 duels)
        count = await supabase_client.get_session_comparison_count(str(session_id))
        sync_queued = False
        if count > 0 and count % 5 == 0:
            import time
            queue_time = time.time()
            # Run ranking update in-process using BackgroundTasks (avoids 1.3s event loop overhead)
            from app.tasks import process_ranking_update
            background_tasks.add_task(process_ranking_update, str(session_id))
            sync_queued = True
            logger.info(f"[TIMING] Queued ranking update for session {session_id} at count={count} (timestamp: {queue_time})")

        # 5. Fetch current convergence to return in response
        details = await supabase_client.get_session_details(str(session_id))
        convergence_score = details.get("convergence_score") or 0

        return ComparisonResponse(
            success=True,
            new_elo_a=new_elo_a,
            new_elo_b=new_elo_b,
            sync_queued=sync_queued,
            convergence_score=convergence_score
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}/comparisons/last", response_model=UndoComparisonResponse)
async def undo_last_comparison(session_id: UUID, background_tasks: BackgroundTasks):
    """
    Undo the last comparison in a session.
    Restores previous ELO values and deletes the comparison record.
    Triggers a ranking recalculation in the background.
    """
    try:
        # 1. Call the RPC to undo the last comparison
        result = await supabase_client.undo_last_comparison(str(session_id))
        
        # 2. Trigger ranking recalculation to update BT strengths
        from app.tasks import process_ranking_update
        background_tasks.add_task(process_ranking_update, str(session_id))
        
        logger.info(f"Undid comparison {result['comparison_id']} in session {session_id}")
        
        return UndoComparisonResponse(
            success=True,
            comparison_id=result["comparison_id"],
            song_a_id=result["song_a_id"],
            song_b_id=result["song_b_id"],
            restored_elo_a=result["restored_elo_a"],
            restored_elo_b=result["restored_elo_b"],
            sync_queued=True
        )
        
    except ValueError as e:
        # No comparison found or can't undo
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to undo comparison: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions", response_model=SessionResponse)
@limiter.limit("10/minute")
async def create_session(request: Request, session_data: SessionCreate, background_tasks: BackgroundTasks):
    """
    Initialize a ranking session.
    1. Normalizes song titles.
    2. Resolves songs in the global catalog.
    3. Links songs to the new session.
    4. Triggers background deep deduplication.
    """
    try:
        # 1. Normalize and pre-deduplicate songs before DB upsert
        # This prevents 'ON CONFLICT' errors when multiple songs normalize to the same key
        unique_songs = {}
        for s in session_data.songs:
            norm_name = normalize_title(s.name)
            key = (s.artist.lower(), norm_name)
            
            # Keep the one with more metadata (Spotify ID or Album)
            score = sum(1 for field in (s.spotify_id, s.album) if field)
            existing_data = unique_songs.get(key)
            if not existing_data or score > existing_data["score"]:
                unique_songs[key] = {
                    "song": s,
                    "score": score,
                    "normalized_name": norm_name
                }

        prepared_songs = [
            {
                "name": item["song"].name,
                "artist": item["song"].artist,
                "album": item["song"].album,
                "normalized_name": item["normalized_name"],
                "spotify_id": item["song"].spotify_id,
                "cover_url": item["song"].cover_url
            }
            for item in unique_songs.values()
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

        # 5. Queue deep deduplication in Redis
        task_queue.enqueue(run_deep_deduplication, session_id)

        return SessionResponse(
            session_id=UUID(session_id),
            count=len(song_ids)
        )

    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))
