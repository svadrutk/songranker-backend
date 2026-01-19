from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, cast, List
import logging
from supabase import create_async_client, AsyncClient
from app.core.config import settings

logger = logging.getLogger(__name__)

class SupabaseDB:
    def __init__(self):
        self.url = settings.effective_supabase_url
        self.key = settings.effective_supabase_key
        self._client: Optional[AsyncClient] = None

    async def get_client(self) -> AsyncClient:
        if self._client is None:
            url = settings.effective_supabase_url
            key = settings.effective_supabase_key
            if not url or not key:
                raise ValueError("Supabase URL and Key must be set in environment")
            self._client = await create_async_client(url, key)
        return self._client

    async def get_ranking(self, user_id: str, release_id: str) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        try:
            response = await client.table("rankings").select("*").eq("user_id", user_id).eq("release_id", release_id).execute()
            return cast(Dict[str, Any], response.data[0]) if response.data else None
        except Exception as e:
            logger.warning(f"Failed to get ranking for {user_id}/{release_id}: {e}")
            return None

    async def get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Fetch a cache entry and return it if it exists (even if expired for SWR)."""
        client = await self.get_client()
        try:
            response = await client.table("api_cache").select("*").eq("key", key).execute()
            if response.data:
                return cast(Dict[str, Any], response.data[0])
            return None
        except Exception as e:
            logger.warning(f"Cache miss/error for {key}: {e}")
            return None

    async def set_cache(self, key: str, data: Any, expires_at: datetime):
        """Upsert a cache entry."""
        client = await self.get_client()
        try:
            await client.table("api_cache").upsert({
                "key": key,
                "data": data,
                "expires_at": expires_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to set cache for {key}: {e}")

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
        payload: Dict[str, Any] = {"status": "active"}
        if user_id:
            payload["user_id"] = user_id
        
        response = await client.table("sessions").insert(payload).execute()
        if not response.data or not isinstance(response.data, list):
            raise ValueError("Failed to create session")
        
        first_row = response.data[0]
        if not isinstance(first_row, dict):
            raise ValueError("Failed to create session - unexpected format")
            
        return str(first_row.get("id"))

    async def link_session_songs(self, session_id: str, song_ids: List[str]):
        """Link a list of songs to a session."""
        client = await self.get_client()
        links = [{"session_id": session_id, "song_id": sid} for sid in song_ids]
        await client.table("session_songs").insert(links).execute()

    async def get_session_songs(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all songs associated with a session."""
        client = await self.get_client()
        response = await client.table("session_songs") \
            .select("song_id, songs(*)") \
            .eq("session_id", session_id) \
            .execute()
        
        results: List[Dict[str, Any]] = []
        data = cast(List[Dict[str, Any]], response.data or [])
        for item in data:
            # Flatten song details
            song_details = item.pop("songs", None)
            if isinstance(song_details, dict):
                results.append({**item, **song_details})
        return results

    async def remove_session_song(self, session_id: str, song_id: str):
        """Remove a song from a session (used during deduplication)."""
        client = await self.get_client()
        await client.table("session_songs") \
            .delete() \
            .eq("session_id", session_id) \
            .eq("song_id", song_id) \
            .execute()

    async def update_comparison_aliases(self, session_id: str, old_song_id: str, new_song_id: str):
        """Update any comparisons that used the duplicate song ID."""
        import asyncio
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

    async def delete_expired_cache(self):
        """Delete cache entries that have been expired for more than 24 hours."""
        client = await self.get_client()
        try:
            # SWR window is usually 24h, so we delete anything expired > 24h ago
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            await client.table("api_cache").delete().lt("expires_at", cutoff).execute()
        except Exception as e:
            logger.error(f"Failed to delete expired cache: {e}")

supabase_client = SupabaseDB()
