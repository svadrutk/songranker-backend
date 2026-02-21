import logging
from itertools import combinations
from typing import Dict, Any
import difflib
from app.clients.supabase_db import supabase_client

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 92.0

def _token_sort_ratio(s1: str, s2: str) -> float:
    """
    Pure Python implementation of token_sort_ratio using difflib.
    Returns score 0-100.
    """
    if not s1 or not s2:
        return 0.0
    
    # 1. Tokenize (lower case, split by whitespace)
    tokens1 = sorted(str(s1).lower().split())
    tokens2 = sorted(str(s2).lower().split())
    
    # 2. Reconstruct strings
    t1 = " ".join(tokens1)
    t2 = " ".join(tokens2)
    
    # 3. Ratio
    # difflib.SequenceMatcher.ratio() returns float [0, 1]
    return difflib.SequenceMatcher(None, t1, t2).ratio() * 100.0

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
            score = _token_sort_ratio(song_a["normalized_name"], song_b["normalized_name"])
            
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
    """Decide which song to keep as the canonical version.

    Scoring: spotify_id and apple_music_id are weighted equally (both are
    platform-specific catalog links). album presence adds metadata richness.
    Tie-break: shorter name (less likely to be a variant title).
    """
    def get_score(s: Dict[str, Any]) -> int:
        return sum(1 for field in ("spotify_id", "apple_music_id", "album") if s.get(field))

    score_a, score_b = get_score(song_a), get_score(song_b)

    if score_a != score_b:
        return (song_a, song_b) if score_a > score_b else (song_b, song_a)
        
    return (song_a, song_b) if len(song_a["name"]) <= len(song_b["name"]) else (song_b, song_a)
