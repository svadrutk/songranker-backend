import httpx
import base64
import time
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.core.utils import normalize_title, DELUXE_KEYWORDS, SKIP_KEYWORDS

class SpotifyClient:
    def __init__(self):
        self.auth_url = "https://accounts.spotify.com/api/token"
        self.base_url = "https://api.spotify.com/v1"
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True
            )
        return self._client

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        """Fetch or refresh the Bearer token."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        auth_str = f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()

        response = await client.post(
            self.auth_url,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {b64_auth}"}
        )
        response.raise_for_status()
        data = response.json()
        
        self._access_token = data["access_token"]
        # Set expiration (subtract 60s for safety)
        self._token_expires_at = time.time() + data["expires_in"] - 60
        return self._access_token

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """Authenticated GET request."""
        active_client = client or await self.get_client()
        token = await self._get_access_token(active_client)
        
        response = await active_client.get(
            f"{self.base_url}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params
        )
        response.raise_for_status()
        return response.json()

    async def search_artist_albums(self, artist_name: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        """
        Search for albums by artist. 
        Note: Spotify's "album" type includes EPs and Singles, so we filter.
        """
        # 1. Search for the artist first to get the exact ID (handles Typos better)
        search_res = await self._get("/search", params={"q": artist_name, "type": "artist", "limit": 1}, client=client)
        artists = search_res.get("artists", {}).get("items", [])
        if not artists:
            return []
            
        artist_id = artists[0]["id"]
        
        # 2. Get Artist's Albums
        # include_groups: album,single,compilation,appears_on
        # We focus on 'album' and 'single' (which covers EPs sometimes)
        params = {
            "include_groups": "album,single", 
            "limit": 50,
            "market": "US" # Enforce a market to avoid duplicates/unplayable versions
        }
        
        albums_res = await self._get(f"/artists/{artist_id}/albums", params=params, client=client)
        raw_albums = albums_res.get("items", [])
        
        # Deduplicate and Clean
        return self._process_albums(raw_albums, artist_name)

    def _process_albums(self, albums: List[Dict[str, Any]], artist_name: str) -> List[Dict[str, Any]]:
        """Deduplicate albums (Spotify returns many versions) and format."""
        deduped = {}
        
        for album in albums:
            title = album.get("name", "")
            if not title: continue
            
            # Skip noise
            if any(kw in title.lower() for kw in SKIP_KEYWORDS):
                continue
            
            # Simple normalization
            norm_title = normalize_title(title)
            is_deluxe = any(kw in title.lower() for kw in DELUXE_KEYWORDS)
            
            # Key collision logic
            if norm_title not in deduped:
                deduped[norm_title] = album
            else:
                existing = deduped[norm_title]
                existing_is_deluxe = any(kw in existing["name"].lower() for kw in DELUXE_KEYWORDS)
                
                # Prefer Deluxe
                if is_deluxe and not existing_is_deluxe:
                    deduped[norm_title] = album
                # Prefer more tracks (we can't see track count in the simple list object easily 
                # without total_tracks, so we use that)
                elif is_deluxe == existing_is_deluxe:
                    if album.get("total_tracks", 0) > existing.get("total_tracks", 0):
                        deduped[norm_title] = album

        results = []
        for album in deduped.values():
            results.append({
                "id": album["id"], # Spotify ID, not MBID
                "title": album["name"],
                "artist": album["artists"][0]["name"] if album["artists"] else artist_name,
                "type": album["album_type"].capitalize(), # "Album", "Single", "Compilation"
                "cover_art": {
                    "front": True,
                    "url": album["images"][0]["url"] if album["images"] else None
                },
                "source": "spotify"
            })
            
        return results

    async def get_album_tracks(self, spotify_id: str, client: Optional[httpx.AsyncClient] = None) -> List[str]:
        """Fetch clean tracklist from Spotify."""
        # Handle paginated tracks (limit is 50)
        all_tracks = []
        url = f"/albums/{spotify_id}/tracks"
        params = {"limit": 50, "market": "US"}
        
        while url:
            # We strip the base URL if next_url is full, or just use the endpoint
            if url.startswith(self.base_url):
                endpoint = url.replace(self.base_url, "")
            else:
                endpoint = url
                
            data = await self._get(endpoint, params=params if not all_tracks else None, client=client)
            items = data.get("items", [])
            all_tracks.extend(items)
            
            url = data.get("next")
            
        return self._clean_tracks(all_tracks)

    def _clean_tracks(self, tracks: List[Dict[str, Any]]) -> List[str]:
        cleaned = []
        seen = set()
        
        for t in tracks:
            name = t.get("name", "")
            if not name: continue
            
            # Spotify doesn't have as much junk as MB, but still good to check
            lower = name.lower()
            if "commentary" in lower or "interview" in lower:
                continue
                
            # Deduplicate by name
            if lower not in seen:
                cleaned.append(name)
                seen.add(lower)
                
        return cleaned

spotify_client = SpotifyClient()
