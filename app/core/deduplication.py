import logging
from typing import List, Dict, Any
from rapidfuzz import fuzz
from app.clients.supabase_db import supabase_client

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 92.0

async def deep_deduplicate_session(session_id: str):
    """
    Background task to find near-duplicate songs in a session and merge them.
    Only merges within the session scope.
    """
    logger.info(f"Starting deep deduplication for session {session_id}")
    
    try:
        songs = await supabase_client.get_session_songs(session_id)
        if len(songs) < 2:
            return

        from itertools import combinations
        removed_ids = set()
        
        # Compare all unique pairs
        for song_a, song_b in combinations(songs, 2):
            id_a, id_b = song_a["song_id"], song_b["song_id"]
            
            if id_a in removed_ids or id_b in removed_ids:
                continue
                
            # Only compare songs by the same artist
            if song_a["artist"].lower() != song_b["artist"].lower():
                continue

            # Calculate similarity between normalized names
            score = fuzz.token_sort_ratio(song_a["normalized_name"], song_b["normalized_name"])
            
            if score >= SIMILARITY_THRESHOLD:
                logger.info(f"Auto-merging duplicates in session {session_id}: '{song_a['name']}' and '{song_b['name']}' (Score: {score})")
                
                keep, remove = _decide_canonical(song_a, song_b)
                
                await supabase_client.remove_session_song(session_id, remove["song_id"])
                await supabase_client.update_comparison_aliases(session_id, remove["song_id"], keep["song_id"])
                
                removed_ids.add(remove["song_id"])
                    
        logger.info(f"Deep deduplication complete for session {session_id}. Removed {len(removed_ids)} duplicates.")
        
    except Exception as e:
        logger.error(f"Error during deep deduplication for session {session_id}: {e}")

def _decide_canonical(song_a: Dict[str, Any], song_b: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Decide which song to keep as the canonical version based on Spotify ID, Album, and name length."""
    a_score = (1 if song_a.get("spotify_id") else 0) + (1 if song_a.get("album") else 0)
    b_score = (1 if song_b.get("spotify_id") else 0) + (1 if song_b.get("album") else 0)

    if a_score > b_score:
        return song_a, song_b
    if b_score > a_score:
        return song_b, song_a
        
    return (song_a, song_b) if len(song_a["name"]) <= len(song_b["name"]) else (song_b, song_a)
