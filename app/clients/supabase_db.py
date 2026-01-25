import asyncio
from typing import Dict, Any, Optional, cast, List
import logging
from supabase import create_async_client, AsyncClient
from postgrest.types import CountMethod
from app.core.config import settings

logger = logging.getLogger(__name__)

class SupabaseDB:
    def __init__(self):
        self.url = settings.effective_supabase_url
        self.key = settings.effective_supabase_key
        self._client: Optional[AsyncClient] = None

    async def get_client(self) -> AsyncClient:
        if self._client is None:
            if not self.url or not self.key:
                raise ValueError("Supabase URL and Key must be set in environment")
            self._client = await create_async_client(self.url, self.key)
        return self._client


    async def get_ranking(self, user_id: str, release_id: str) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        try:
            response = await client.table("rankings") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("release_id", release_id) \
                .execute()
            return cast(Dict[str, Any], response.data[0]) if response.data else None
        except Exception as e:
            logger.warning(f"Failed to get ranking for {user_id}/{release_id}: {e}")
            return None


    async def bulk_upsert_songs(self, songs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Upsert a list of songs into the global catalog.
        Uses the (artist, normalized_name) unique constraint.
        """
        client = await self.get_client()
        try:
            # Upsert returns the inserted/updated rows
            response = await client.table("songs").upsert(
                songs,
                on_conflict="artist,normalized_name"
            ).execute()
            return cast(List[Dict[str, Any]], response.data)
        except Exception as e:
            logger.error(f"Failed bulk upsert of songs: {e}")
            raise

    async def create_session(self, user_id: Optional[str] = None) -> str:
        """Create a new session and return its ID."""
        client = await self.get_client()
        payload = {"status": "active"}
        if user_id:
            payload["user_id"] = user_id
        
        response = await client.table("sessions").insert(payload).execute()
        if not response.data or not isinstance(response.data, list):
            raise ValueError("Failed to create session: No data returned")
        
        first_row = response.data[0]
        if not isinstance(first_row, dict):
            raise ValueError("Failed to create session: Unexpected response format")
            
        return str(first_row.get("id"))


    async def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get summarized sessions for a user using a optimized join.
        This fetches sessions, counts, and primary artist in one query.
        """
        client = await self.get_client()
        
        response = await client.rpc("get_user_session_summaries", {
            "p_user_id": user_id
        }).execute()
        
        data = cast(List[Dict[str, Any]], response.data or [])
        if not isinstance(data, list):
            return []

        # Map the 'out_' prefixed columns back to expected names
        results = [
            {
                "session_id": s["out_session_id"],
                "created_at": s["out_created_at"],
                "primary_artist": s["out_primary_artist"],
                "song_count": s["out_song_count"],
                "comparison_count": s["out_comparison_count"],
                "convergence_score": s.get("out_convergence_score", 0),
                "top_album_covers": s["out_top_album_covers"] or []
            }
            for s in data
        ]
        if results:
            logger.info(f"[DB] Session {results[0]['session_id']} artist {results[0]['primary_artist']} convergence: {results[0]['convergence_score']}")
        return results


    async def get_session_comparison_count(self, session_id: str) -> int:
        """Get the total number of comparisons for a session."""
        client = await self.get_client()
        response = await client.table("comparisons") \
            .select("id", count=CountMethod.exact) \
            .eq("session_id", session_id) \
            .execute()
        return response.count or 0

    async def link_session_songs(self, session_id: str, song_ids: List[str]):
        """Link a list of songs to a session."""
        client = await self.get_client()
        links = [{"session_id": str(session_id), "song_id": str(sid)} for sid in song_ids]
        try:
            response = await client.table("session_songs").insert(links).execute()
            if not response.data:
                logger.error(f"Failed to link songs: No data returned. Possible RLS or Schema issue.")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to link songs to session {session_id}: {e}")
            raise

    async def get_session_songs(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all songs associated with a session, including local_elo."""
        client = await self.get_client()
        try:
            res = await client.table("session_songs") \
                .select("song_id, local_elo, bt_strength, songs(*)") \
                .eq("session_id", str(session_id)) \
                .execute()
            
            if not res.data or not isinstance(res.data, list):
                return []
            
            results = []
            for item in res.data:
                if not isinstance(item, dict):
                    continue
                
                songs_data = item.get("songs")
                if not songs_data:
                    continue
                
                details = songs_data[0] if isinstance(songs_data, list) else songs_data
                if not isinstance(details, dict):
                    continue
                
                # Merge session-specific stats with global song details
                song_info = {
                    "song_id": str(item.get("song_id", "")),
                    "local_elo": item.get("local_elo", 1500.0),
                    "bt_strength": item.get("bt_strength"),
                }
                song_info.update({k: v for k, v in details.items() if k != "id"})
                results.append(song_info)

            return results
        except Exception as e:
            logger.error(f"Database error in get_session_songs: {e}")
            return []


    async def get_session_details(self, session_id: str) -> Dict[str, Any]:
        """Get session metadata including convergence."""
        client = await self.get_client()
        try:
            response = await client.table("sessions") \
                .select("*") \
                .eq("id", str(session_id)) \
                .maybe_single() \
                .execute()
            
            if response and hasattr(response, "data") and response.data:
                return cast(Dict[str, Any], response.data)
            return {}
        except Exception as e:
            logger.error(f"Database error in get_session_details: {e}")
            return {}

    async def get_session_song_elos(self, session_id: str, song_ids: List[str]) -> List[Dict[str, Any]]:
        """Get local_elo for specific songs in a session."""
        client = await self.get_client()
        try:
            # song_ids should be a list of strings (UUIDs)
            response = await client.table("session_songs") \
                .select("song_id, local_elo") \
                .eq("session_id", str(session_id)) \
                .in_("song_id", [str(sid) for sid in song_ids]) \
                .execute()
            return cast(List[Dict[str, Any]], response.data or [])
        except Exception as e:
            logger.error(f"Error in get_session_song_elos: {e}")
            return []

    async def record_comparison_and_update_elo(
        self, 
        session_id: str, 
        song_a_id: str, 
        song_b_id: str, 
        winner_id: Optional[str], 
        is_tie: bool,
        new_elo_a: float,
        new_elo_b: float,
        decision_time_ms: Optional[int] = None
    ):
        """
        Record a comparison and update Elos in a single transaction-like block.
        Ideally this would be a single RPC call to handle atomicity.
        """
        client = await self.get_client()
        
        # We use RPC for atomicity and efficiency
        # This requires a 'record_duel' function to be defined in Supabase/Postgres
        payload = {
            "p_session_id": session_id,
            "p_song_a_id": song_a_id,
            "p_song_b_id": song_b_id,
            "p_winner_id": winner_id,
            "p_is_tie": is_tie,
            "p_new_elo_a": new_elo_a,
            "p_new_elo_b": new_elo_b
        }
        
        if decision_time_ms is not None:
            payload["p_decision_time_ms"] = decision_time_ms

        await client.rpc("record_duel", payload).execute()


    async def get_session_comparisons(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all raw duel results for a session."""
        client = await self.get_client()
        response = await client.table("comparisons") \
            .select("song_a_id, song_b_id, winner_id, is_tie, decision_time_ms") \
            .eq("session_id", session_id) \
            .execute()
        return cast(List[Dict[str, Any]], response.data or [])

    async def update_session_ranking(
        self, 
        session_id: str, 
        updates: List[Dict[str, Any]],
        convergence_score: int
    ):
        """
        Bulk update song rankings and session convergence.
        
        updates: List of dicts with {song_id, bt_strength, local_elo}
        """
        client = await self.get_client()
        
        # 1. Update session songs (bulk upsert is efficient)
        # We need to include session_id in the updates to match the composite key (session_id, song_id)
        if updates:
            enriched_updates = [{**u, "session_id": session_id} for u in updates]
            await client.table("session_songs").upsert(
                enriched_updates,
                on_conflict="session_id,song_id"
            ).execute()
            
        # 2. Update session convergence
        await client.table("sessions").update({
            "convergence_score": convergence_score,
            "last_active_at": "now()"
        }).eq("id", session_id).execute()

    async def remove_session_song(self, session_id: str, song_id: str):
        """Remove a song from a session (used during deduplication)."""
        client = await self.get_client()
        await client.table("session_songs") \
            .delete() \
            .eq("session_id", session_id) \
            .eq("song_id", song_id) \
            .execute()

    async def delete_session(self, session_id: str):
        """Delete a session and all its associated data."""
        client = await self.get_client()
        # We assume cascading deletes are handled by the database schema
        # (comparisons and session_songs linked via ON DELETE CASCADE)
        await client.table("sessions") \
            .delete() \
            .eq("id", session_id) \
            .execute()

    async def update_comparison_aliases(self, session_id: str, old_song_id: str, new_song_id: str):
        """Update any comparisons that used the duplicate song ID."""
        client = await self.get_client()
        
        # Parallelize the three update operations
        await asyncio.gather(
            client.table("comparisons").update({"winner_id": new_song_id})
                .eq("session_id", session_id).eq("winner_id", old_song_id).execute(),
            client.table("comparisons").update({"song_a_id": new_song_id})
                .eq("session_id", session_id).eq("song_a_id", old_song_id).execute(),
            client.table("comparisons").update({"song_b_id": new_song_id})
                .eq("session_id", session_id).eq("song_b_id", old_song_id).execute()
        )

    # ==================== Global Leaderboard Methods ====================

    async def get_artist_songs(self, artist: str) -> List[Dict[str, Any]]:
        """Get all songs for a specific artist with their global stats."""
        client = await self.get_client()
        response = await client.rpc("get_artist_songs", {
            "p_artist": artist
        }).execute()
        return cast(List[Dict[str, Any]], response.data or [])

    async def get_artist_comparisons(self, artist: str) -> List[Dict[str, Any]]:
        """Get all comparisons for songs by a specific artist across all sessions."""
        client = await self.get_client()
        response = await client.rpc("get_artist_comparisons", {
            "p_artist": artist
        }).execute()
        return cast(List[Dict[str, Any]], response.data or [])

    async def update_global_rankings(self, updates: List[Dict[str, Any]]):
        """
        Bulk update global rankings for songs.
        
        updates: List of dicts with {song_id, global_elo, global_bt_strength, global_votes_count}
        """
        if not updates:
            return
            
        client = await self.get_client()
        
        # Update each song individually (Supabase doesn't support bulk update easily)
        # This is acceptable because global updates happen in background
        for u in updates:
            await client.table("songs").update({
                "global_elo": u["global_elo"],
                "global_bt_strength": u["global_bt_strength"],
                "global_votes_count": u.get("global_votes_count", 0)
            }).eq("id", str(u["song_id"])).execute()
        
        logger.info(f"Successfully updated global rankings for {len(updates)} songs")

    async def get_artist_stats(self, artist: str) -> Optional[Dict[str, Any]]:
        """Get statistics for an artist including last update timestamp."""
        client = await self.get_client()
        response = await client.table("artist_stats") \
            .select("*") \
            .eq("artist", artist) \
            .limit(1) \
            .execute()
        
        if response and hasattr(response, "data") and response.data and len(response.data) > 0:
            return cast(Dict[str, Any], response.data[0])
        return None

    async def get_artist_total_comparisons(self, artist: str) -> int:
        """
        Get the total number of comparisons for an artist across all sessions.
        This includes both processed (in global rankings) and pending comparisons.
        """
        client = await self.get_client()
        response = await client.rpc("get_artist_comparisons", {
            "p_artist": artist
        }).execute()
        
        comparisons = cast(List[Dict[str, Any]], response.data or [])
        return len(comparisons)

    async def upsert_artist_stats(self, artist: str, comparison_count: int):
        """Update or insert artist statistics."""
        client = await self.get_client()
        await client.table("artist_stats").upsert({
            "artist": artist,
            "last_global_update_at": "now()",
            "total_comparisons_count": comparison_count
        }, on_conflict="artist").execute()
        
        logger.info(f"Updated artist stats for {artist}: {comparison_count} comparisons")

    async def get_leaderboard(self, artist: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the global leaderboard for an artist."""
        client = await self.get_client()
        response = await client.table("songs") \
            .select("id, name, artist, album, cover_url, global_elo, global_bt_strength, global_votes_count") \
            .eq("artist", artist) \
            .order("global_elo", desc=True) \
            .limit(limit) \
            .execute()
        
        return cast(List[Dict[str, Any]], response.data or [])

    async def get_session_primary_artist(self, session_id: str) -> Optional[str]:
        """Get the primary artist for a session by finding the most common artist."""
        client = await self.get_client()
        try:
            # Get all songs in the session with their artists
            response = await client.table("session_songs") \
                .select("songs(artist)") \
                .eq("session_id", session_id) \
                .execute()
            
            if not response.data:
                return None
            
            # Count artist occurrences
            artist_counts: Dict[str, int] = {}
            for item in response.data:
                if not isinstance(item, dict):
                    continue
                    
                songs_data = item.get("songs")
                if not songs_data:
                    continue
                
                song_detail = songs_data[0] if isinstance(songs_data, list) else songs_data
                if isinstance(song_detail, dict):
                    artist = song_detail.get("artist")
                    if artist and isinstance(artist, str):
                        artist_counts[artist] = artist_counts.get(artist, 0) + 1
            
            if not artist_counts:
                return None
            
            # Return the most common artist
            return max(artist_counts.items(), key=lambda x: x[1])[0]
            
        except Exception as e:
            logger.error(f"Error fetching primary artist for session {session_id}: {e}")
            return None


supabase_client = SupabaseDB()
