from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, cast
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
