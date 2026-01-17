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

    async def get_ranking(self, user_id: str, release_id: str, client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
        if not self.url:
            return None
        
        active_client = client or httpx.AsyncClient()
        try:
            response = await active_client.get(
                f"{self.url}/rest/v1/rankings",
                headers=self.headers,
                params={"user_id": f"eq.{user_id}", "release_id": f"eq.{release_id}"}
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None
        finally:
            if not client: # Only close if we created it
                await active_client.aclose()

supabase_client = SupabaseClient()
