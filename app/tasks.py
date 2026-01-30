import asyncio
import logging
from typing import Dict, Any
from app.core.deduplication import deep_deduplicate_session
from app.core.ranking import RankingManager
from app.clients.supabase_db import supabase_client
from app.core.cache import cache
from app.core.queue import task_queue, leaderboard_queue
from app.core.global_ranking_config import (
    GLOBAL_UPDATE_INTERVAL_MINUTES,
    get_global_update_lock_key
)
from app.core.global_ranking_utils import (
    should_trigger_global_update,
    get_seconds_since_update
)

logger = logging.getLogger(__name__)

# In-memory set to track artists currently being updated
# This provides per-worker-process deduplication, while Redis locks provide cross-worker coordination
_global_update_locks: set = set()

def _run_async_task(coro) -> Any:
    """
    Helper to run async tasks in a synchronous worker environment.
    
    Args:
        coro: The coroutine to run
    
    Returns:
        The result of the coroutine
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _maybe_trigger_global_update(session_id: str) -> None:
    """
    Check if the session's primary artist needs a global ranking update.
    Triggers update if last update was more than GLOBAL_UPDATE_INTERVAL_MINUTES ago.
    
    Args:
        session_id: The session ID to check
    """
    # Get the primary artist for this session
    artist = await supabase_client.get_session_primary_artist(session_id)
    if not artist:
        logger.warning(f"[GLOBAL] Could not determine primary artist for session_id={session_id}")
        return
    
    # Check if this artist is already being updated (per-worker deduplication)
    # Use normalized name for consistency
    norm_artist = artist.lower()
    if norm_artist in _global_update_locks:
        logger.debug(f"[GLOBAL] Artist artist='{artist}' already being updated in this worker - skipping")
        return
    
    # Check when this artist was last updated
    stats = await supabase_client.get_artist_stats(artist)
    last_update = stats.get("last_global_update_at") if stats else None
    
    if last_update:
        seconds_since = get_seconds_since_update(last_update)
        logger.info(
            f"[GLOBAL] Time check for '{artist}': {seconds_since/60:.1f}m since last update "
            f"(Interval: {GLOBAL_UPDATE_INTERVAL_MINUTES}m)"
        )

    # Use shared utility to check if update should be triggered
    # Pass pending_comparisons=1 to indicate there's at least one new comparison
    if not await should_trigger_global_update(artist, last_update, pending_comparisons=1):
        return
    
    # Enqueue the update
    _global_update_locks.add(norm_artist)
    leaderboard_queue.enqueue(run_global_ranking_update, artist)
    
    if last_update:
        time_since = get_seconds_since_update(last_update)
        logger.info(
            f"[GLOBAL] Enqueued global ranking update for artist='{artist}' "
            f"(last_updated={time_since:.0f}s ago)"
        )
    else:
        logger.info(f"[GLOBAL] Enqueued global ranking update for artist='{artist}' (first update)")

def run_deep_deduplication(session_id: str) -> None:
    """Synchronous wrapper for deduplication task."""
    logger.info(f"[WORKER] Processing deduplication for session_id={session_id}")
    try:
        _run_async_task(deep_deduplicate_session(session_id))
    except Exception as e:
        logger.error(f"[WORKER] Failed deduplication for session_id={session_id}: {e}")
        raise

async def process_ranking_update(session_id: str) -> None:
    """Compute and persist session-level Bradley-Terry rankings."""
    import time
    start_time = time.time()
    logger.info(f"[TIMING] Starting ranking update for session_id={session_id}")
    
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
        logger.warning(f"[RANKING] No songs found for session_id={session_id}")
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
    
    logger.info(f"[RANKING] Session session_id={session_id}: quantity={quantity_score:.2f}, stability={stability_score:.2f}, convergence={convergence_score}")
    
    # 6. Persist results to database
    persist_start = time.time()
    await supabase_client.update_session_ranking(session_id, updates, convergence_score)
    persist_time = (time.time() - persist_start) * 1000
    logger.info(f"[TIMING] Database persist took {persist_time:.2f}ms")
    
    total_time = (time.time() - start_time) * 1000
    logger.info(f"[TIMING] Completed ranking update for session_id={session_id} in {total_time:.2f}ms")
    
    # 7. Trigger global ranking update if enough time has passed
    await _maybe_trigger_global_update(session_id)

def run_ranking_update(session_id: str) -> None:
    """Synchronous wrapper for ranking update task."""
    logger.info(f"[WORKER] Processing ranking update for session_id={session_id}")
    try:
        _run_async_task(process_ranking_update(session_id))
    except Exception as e:
        logger.error(f"[WORKER] Failed ranking update for session_id={session_id}: {e}")
        raise

async def process_global_ranking(artist: str) -> None:
    """
    Compute global rankings for all songs by a specific artist.
    Aggregates comparisons across all user sessions.
    
    Args:
        artist: The artist name
    """
    import time
    start_time = time.time()
    logger.info(f"[GLOBAL] Starting global ranking update for artist='{artist}'")
    
    # 1. Fetch all songs and comparisons for this artist in parallel
    fetch_start = time.time()
    songs, comparisons = await asyncio.gather(
        supabase_client.get_artist_songs(artist),
        supabase_client.get_artist_comparisons(artist)
    )
    fetch_time = (time.time() - fetch_start) * 1000
    logger.info(f"[GLOBAL] Fetched songs={len(songs)}, comparisons={len(comparisons)} in {fetch_time:.2f}ms for artist='{artist}'")
    
    if not songs:
        logger.warning(f"[GLOBAL] No songs found for artist='{artist}'")
        return
    
    # 2. Handle case with no comparisons yet - initialize with defaults
    if not comparisons:
        logger.warning(f"[GLOBAL] No comparisons found for artist='{artist}'")
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
    
    # 7. Invalidate leaderboard cache for this artist
    # Use lowercase artist name for pattern to match normalized cache keys
    norm_artist = artist.lower()
    await cache.delete_pattern(f"leaderboard:{norm_artist}:*")
    logger.info(f"[GLOBAL] Invalidated leaderboard cache for artist='{artist}' (normalized='{norm_artist}')")
    
    total_time = (time.time() - start_time) * 1000
    logger.info(f"[GLOBAL] Completed global ranking for artist='{artist}' in {total_time:.2f}ms")

def _release_redis_lock(lock_key: str) -> None:
    """
    Release Redis lock, handling errors gracefully.
    
    Args:
        lock_key: The Redis lock key to release
    """
    import redis as redis_sync
    from app.core.config import settings
    
    try:
        redis_conn = redis_sync.from_url(settings.REDIS_URL)
        redis_conn.delete(lock_key)
        logger.debug(f"[GLOBAL] Released Redis lock: {lock_key}")
    except Exception as e:
        logger.error(f"[GLOBAL] Failed to release Redis lock '{lock_key}': {e}")


def _cleanup_locks(artist: str) -> None:
    """
    Clean up both in-memory and Redis locks.
    
    Uses two lock mechanisms:
    - In-memory lock: Prevents duplicate enqueues within this worker process
    - Redis lock: Prevents duplicate updates across all worker instances
    
    Args:
        artist: The artist name
    """
    # Remove in-memory lock (use normalized name)
    _global_update_locks.discard(artist.lower())
    
    # Remove Redis lock
    lock_key = get_global_update_lock_key(artist)
    _release_redis_lock(lock_key)


def run_global_ranking_update(artist: str) -> None:
    """
    Synchronous wrapper for global ranking update task.
    
    Args:
        artist: The artist name
    """
    logger.info(f"[WORKER] Processing global ranking update for artist='{artist}'")
    
    try:
        _run_async_task(process_global_ranking(artist))
    except Exception as e:
        logger.error(f"[WORKER] Failed global ranking for artist='{artist}': {e}")
        # Only cleanup locks on failure so we can retry
        # On success, we let the Redis lock expire naturally to provide a cooldown
        _cleanup_locks(artist)
        raise
    finally:
        # Remove only the in-memory lock for this worker process
        # This allows other tasks to be enqueued in this worker, but they will
        # still be blocked by the Redis lock in the API layer.
        _global_update_locks.discard(artist.lower())

def run_spotify_method(method_name: str, **kwargs) -> Any:
    """
    Worker task to execute Spotify client methods.
    This ensures all Spotify API calls are serialized through a single worker,
    providing natural rate limiting across all Gunicorn instances.
    """
    from app.clients.spotify import spotify_client
    logger.info(f"[SPOTIFY WORKER] Executing method: {method_name} with args: {kwargs}")
    
    try:
        method = getattr(spotify_client, method_name)
        # Remove 'client' from kwargs if it exists because the worker uses its own client
        kwargs.pop('client', None)
        result = _run_async_task(method(**kwargs))
        logger.info(f"[SPOTIFY WORKER] Successfully completed: {method_name}")
        return result
    except Exception as e:
        logger.error(f"[SPOTIFY WORKER] Failed to execute {method_name}: {e}")
        raise
