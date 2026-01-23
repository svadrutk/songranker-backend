import asyncio
import logging
from app.core.deduplication import deep_deduplicate_session
from app.core.ranking import RankingManager
from app.clients.supabase_db import supabase_client

logger = logging.getLogger(__name__)

def _run_async_task(coro):
    """Helper to run async tasks in a synchronous worker environment."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def run_deep_deduplication(session_id: str):
    """Synchronous wrapper for deduplication task."""
    logger.info(f"Worker processing deduplication for session {session_id}")
    try:
        _run_async_task(deep_deduplicate_session(session_id))
    except Exception as e:
        logger.error(f"Worker failed deduplication for {session_id}: {e}")
        raise

async def process_ranking_update(session_id: str):
    """Async logic for ranking update."""
    import time
    start_time = time.time()
    logger.info(f"[TIMING] Starting ranking update for session {session_id}")
    
    # 1. Fetch Data
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

    # 2. Get Previous Ranking (for stability)
    prev_ranking = sorted(
        songs, 
        key=lambda x: x.get("bt_strength") or 0.0, 
        reverse=True
    )
    prev_top_ids = [str(s["song_id"]) for s in prev_ranking]

    # 3. Compute Bradley-Terry with Warm Start
    bt_start = time.time()
    initial_p = {
        str(s["song_id"]): float(s.get("bt_strength") or 1.0) 
        for s in songs
    }
    song_ids = [str(s["song_id"]) for s in songs]
    bt_scores = RankingManager.compute_bradley_terry(
        song_ids, 
        comparisons, 
        initial_p=initial_p
    )
    bt_time = (time.time() - bt_start) * 1000
    logger.info(f"[TIMING] Bradley-Terry computation took {bt_time:.2f}ms")
    
    # 4. Prepare Updates
    updates = []
    curr_ranking_list = []
    
    for sid, strength in bt_scores.items():
        elo = RankingManager.bt_to_elo(strength)
        updates.append({
            "song_id": sid,
            "bt_strength": strength,
            "local_elo": elo
        })
        curr_ranking_list.append((sid, strength))
        
    curr_ranking_list.sort(key=lambda x: x[1], reverse=True)
    curr_top_ids = [x[0] for x in curr_ranking_list]
    
    # 5. Calculate Convergence
    quantity_score = RankingManager.calculate_progress(total_duels, len(songs))
    stability_score = RankingManager.calculate_stability_score(prev_top_ids, curr_top_ids)
    convergence_score = RankingManager.calculate_final_convergence(quantity_score, stability_score)
    
    logger.info(f"Session {session_id}: Quantity={quantity_score:.2f}, Stability={stability_score:.2f}, Final={convergence_score}")
    
    # 6. Persist Results
    persist_start = time.time()
    await supabase_client.update_session_ranking(session_id, updates, convergence_score)
    persist_time = (time.time() - persist_start) * 1000
    logger.info(f"[TIMING] Database persist took {persist_time:.2f}ms")
    
    total_time = (time.time() - start_time) * 1000
    logger.info(f"[TIMING] ✅ Completed ranking update for session {session_id} in {total_time:.2f}ms")

def run_ranking_update(session_id: str):
    """Synchronous wrapper for ranking update task."""
    logger.info(f"Worker processing ranking update for session {session_id}")
    try:
        _run_async_task(process_ranking_update(session_id))
    except Exception as e:
        logger.error(f"Worker failed ranking update for {session_id}: {e}")
        raise
