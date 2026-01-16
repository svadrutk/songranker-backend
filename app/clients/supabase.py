import httpx
from typing import Dict, Any, Optional
from app.core.config import settings

class SupabaseClient:
    def __init__(self):
        self.url = settings.SUPABASE_URL
        self.key = settings.SUPABASE_SERVICE_ROLE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    async def get_ranking(self, user_id: str, release_id: str) -> Optional[Dict[str, Any]]:
        if not self.url: return None
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.url}/rest/v1/rankings",
                headers=self.headers,
                params={"user_id": f"eq.{user_id}", "release_id": f"eq.{release_id}"}
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None

supabase_client = SupabaseClient()
