import asyncio
import logging
from typing import Dict
from datetime import datetime, timedelta, timezone
from app.core.deduplication import deep_deduplicate_session
from app.core.ranking import RankingManager
from app.clients.supabase_db import supabase_client
from app.core.queue import task_queue

logger = logging.getLogger(__name__)

# Global ranking update interval (in minutes)
GLOBAL_UPDATE_INTERVAL_MINUTES = 10

# In-memory set to track artists currently being updated (prevents race conditions)
_global_update_locks: set = set()

def _run_async_task(coro):
    """Helper to run async tasks in a synchronous worker environment."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _maybe_trigger_global_update(session_id: str):
    """
    Check if the session's primary artist needs a global ranking update.
    Triggers update if last update was more than GLOBAL_UPDATE_INTERVAL_MINUTES ago.
    """
    # Get the primary artist for this session
    artist = await supabase_client.get_session_primary_artist(session_id)
    if not artist:
        logger.warning(f"Could not determine primary artist for session {session_id}")
        return
    
    # Check if this artist is already being updated (race condition prevention)
    if artist in _global_update_locks:
        logger.debug(f"[GLOBAL] Artist '{artist}' is already being updated - skipping")
        return
    
    # Check when this artist was last updated
    stats = await supabase_client.get_artist_stats(artist)
    
    if not stats:
        # Never updated before - trigger update
        _global_update_locks.add(artist)
        task_queue.enqueue(run_global_ranking_update, artist)
        logger.info(f"[GLOBAL] Enqueued global ranking update for artist: {artist}")
        return
    
    # Check if enough time has passed since last update
    last_update = stats.get("last_global_update_at")
    if not last_update:
        return
        
    # Parse the timestamp (comes as ISO string from Supabase)
    # Always use UTC timezone for comparison
    if isinstance(last_update, str):
        last_update_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
    else:
        last_update_dt = last_update
    
    time_since_update = datetime.now(timezone.utc) - last_update_dt
    interval_threshold = timedelta(minutes=GLOBAL_UPDATE_INTERVAL_MINUTES)
    
    if time_since_update >= interval_threshold:
        _global_update_locks.add(artist)
        task_queue.enqueue(run_global_ranking_update, artist)
        logger.info(f"[GLOBAL] Enqueued global ranking update for artist: {artist} (last updated {time_since_update.total_seconds():.0f}s ago)")
    else:
        logger.debug(f"[GLOBAL] Artist '{artist}' updated recently ({time_since_update.total_seconds():.0f}s ago) - skipping")

def run_deep_deduplication(session_id: str):
    """Synchronous wrapper for deduplication task."""
    logger.info(f"Worker processing deduplication for session {session_id}")
    try:
        _run_async_task(deep_deduplicate_session(session_id))
    except Exception as e:
        logger.error(f"Worker failed deduplication for {session_id}: {e}")
        raise

async def process_ranking_update(session_id: str):
    """Compute and persist session-level Bradley-Terry rankings."""
    import time
    start_time = time.time()
    logger.info(f"[TIMING] Starting ranking update for session {session_id}")
    
    # 1. Fetch all session data in parallel
    fetch_start = time.time()
    songs, comparisons, total_duels = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id),
        supabase_client.get_session_comparison_count(session_id)
    )
    fetch_time = (time.time() - fetch_start) * 1000
    logger.info(f"[TIMING] Data fetch took {fetch_time:.2f}ms")
    
    if not songs:
        logger.warning(f"No songs found for session {session_id}")
        return

    # 2. Get previous ranking for stability calculation
    prev_ranking = sorted(songs, key=lambda x: x.get("bt_strength") or 0.0, reverse=True)
    prev_top_ids = [str(s["song_id"]) for s in prev_ranking]

    # 3. Compute Bradley-Terry scores with warm start from previous values
    bt_start = time.time()
    initial_p = {str(s["song_id"]): float(s.get("bt_strength") or 1.0) for s in songs}
    song_ids = [str(s["song_id"]) for s in songs]
    bt_scores = RankingManager.compute_bradley_terry(song_ids, comparisons, initial_p=initial_p)
    bt_time = (time.time() - bt_start) * 1000
    logger.info(f"[TIMING] Bradley-Terry computation took {bt_time:.2f}ms")
    
    # 4. Build updates and current ranking
    updates = []
    curr_ranking_list = []
    
    for sid, strength in bt_scores.items():
        elo = RankingManager.bt_to_elo(strength)
        updates.append({"song_id": sid, "bt_strength": strength, "local_elo": elo})
        curr_ranking_list.append((sid, strength))
        
    curr_ranking_list.sort(key=lambda x: x[1], reverse=True)
    curr_top_ids = [x[0] for x in curr_ranking_list]
    
    # 5. Calculate convergence score
    quantity_score = RankingManager.calculate_progress(total_duels, len(songs))
    stability_score = RankingManager.calculate_stability_score(prev_top_ids, curr_top_ids)
    convergence_score = RankingManager.calculate_final_convergence(quantity_score, stability_score)
    
    logger.info(f"Session {session_id}: Quantity={quantity_score:.2f}, Stability={stability_score:.2f}, Final={convergence_score}")
    
    # 6. Persist results to database
    persist_start = time.time()
    await supabase_client.update_session_ranking(session_id, updates, convergence_score)
    persist_time = (time.time() - persist_start) * 1000
    logger.info(f"[TIMING] Database persist took {persist_time:.2f}ms")
    
    total_time = (time.time() - start_time) * 1000
    logger.info(f"[TIMING] ✅ Completed ranking update for session {session_id} in {total_time:.2f}ms")
    
    # 7. Trigger global ranking update if enough time has passed
    await _maybe_trigger_global_update(session_id)

def run_ranking_update(session_id: str):
    """Synchronous wrapper for ranking update task."""
    logger.info(f"Worker processing ranking update for session {session_id}")
    try:
        _run_async_task(process_ranking_update(session_id))
    except Exception as e:
        logger.error(f"Worker failed ranking update for {session_id}: {e}")
        raise

async def process_global_ranking(artist: str):
    """
    Compute global rankings for all songs by a specific artist.
    Aggregates comparisons across all user sessions.
    """
    import time
    start_time = time.time()
    logger.info(f"[GLOBAL] Starting global ranking update for artist: {artist}")
    
    # 1. Fetch all songs and comparisons for this artist in parallel
    fetch_start = time.time()
    songs, comparisons = await asyncio.gather(
        supabase_client.get_artist_songs(artist),
        supabase_client.get_artist_comparisons(artist)
    )
    fetch_time = (time.time() - fetch_start) * 1000
    logger.info(f"[GLOBAL] Fetched {len(songs)} songs and {len(comparisons)} comparisons in {fetch_time:.2f}ms")
    
    if not songs:
        logger.warning(f"[GLOBAL] No songs found for artist: {artist}")
        return
    
    # 2. Handle case with no comparisons yet - initialize with defaults
    if not comparisons:
        logger.warning(f"[GLOBAL] No comparisons found for artist: {artist}")
        updates = [
            {
                "song_id": str(s["song_id"]),
                "global_elo": 1500.0,
                "global_bt_strength": 1.0,
                "global_votes_count": 0
            }
            for s in songs
        ]
        await asyncio.gather(
            supabase_client.update_global_rankings(updates),
            supabase_client.upsert_artist_stats(artist, 0)
        )
        return
    
    # 3. Compute Bradley-Terry scores with warm start from previous global values
    bt_start = time.time()
    initial_p = {str(s["song_id"]): float(s.get("global_bt_strength") or 1.0) for s in songs}
    song_ids = [str(s["song_id"]) for s in songs]
    bt_scores = RankingManager.compute_bradley_terry(song_ids, comparisons, initial_p=initial_p)
    bt_time = (time.time() - bt_start) * 1000
    logger.info(f"[GLOBAL] Bradley-Terry computation took {bt_time:.2f}ms")
    
    # 4. Count votes per song (each comparison = 1 vote for both songs)
    vote_counts: Dict[str, int] = {sid: 0 for sid in song_ids}
    for comp in comparisons:
        song_a = str(comp.get("song_a_id", ""))
        song_b = str(comp.get("song_b_id", ""))
        if song_a in vote_counts:
            vote_counts[song_a] += 1
        if song_b in vote_counts:
            vote_counts[song_b] += 1
    
    # 5. Build updates with Elo and vote counts
    updates = []
    for sid, strength in bt_scores.items():
        elo = RankingManager.bt_to_elo(strength)
        updates.append({
            "song_id": sid,
            "global_elo": elo,
            "global_bt_strength": strength,
            "global_votes_count": vote_counts.get(sid, 0)
        })
    
    # 6. Persist results to database
    persist_start = time.time()
    await asyncio.gather(
        supabase_client.update_global_rankings(updates),
        supabase_client.upsert_artist_stats(artist, len(comparisons))
    )
    persist_time = (time.time() - persist_start) * 1000
    logger.info(f"[GLOBAL] Database persist took {persist_time:.2f}ms")
    
    total_time = (time.time() - start_time) * 1000
    logger.info(f"[GLOBAL] ✅ Completed global ranking for {artist} in {total_time:.2f}ms")

def run_global_ranking_update(artist: str):
    """Synchronous wrapper for global ranking update task."""
    logger.info(f"Worker processing global ranking update for artist: {artist}")
    try:
        _run_async_task(process_global_ranking(artist))
    except Exception as e:
        logger.error(f"Worker failed global ranking for {artist}: {e}")
        raise
    finally:
        # Remove lock when task completes (success or failure)
        _global_update_locks.discard(artist)
