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
    logger.info(f"Starting ranking update for session {session_id}")
    
    # 1. Fetch Data
    songs, comparisons, total_duels = await asyncio.gather(
        supabase_client.get_session_songs(session_id),
        supabase_client.get_session_comparisons(session_id),
        supabase_client.get_session_comparison_count(session_id)
    )
    
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

    # 3. Compute Bradley-Terry
    song_ids = [str(s["song_id"]) for s in songs]
    bt_scores = RankingManager.compute_bradley_terry(song_ids, comparisons)
    
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
    await supabase_client.update_session_ranking(session_id, updates, convergence_score)
    logger.info(f"Completed ranking update for session {session_id}")

def run_ranking_update(session_id: str):
    """Synchronous wrapper for ranking update task."""
    logger.info(f"Worker processing ranking update for session {session_id}")
    try:
        _run_async_task(process_ranking_update(session_id))
    except Exception as e:
        logger.error(f"Worker failed ranking update for {session_id}: {e}")
        raise
