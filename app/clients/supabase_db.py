from datetime import datetime, timezone
from typing import Dict, Any, Optional, cast
from supabase import create_async_client, AsyncClient
from app.core.config import settings

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
        except Exception:
            return None

    async def get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Fetch a cache entry and return it if it exists (even if expired for SWR)."""
        client = await self.get_client()
        try:
            response = await client.table("api_cache").select("*").eq("key", key).execute()
            if response.data:
                return cast(Dict[str, Any], response.data[0])
            return None
        except Exception:
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
        except Exception:
            pass

supabase_client = SupabaseDB()
