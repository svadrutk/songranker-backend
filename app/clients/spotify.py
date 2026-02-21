import httpx
import base64
import time
import re
import json
import logging
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.core.utils import normalize_title, DELUXE_KEYWORDS, SKIP_KEYWORDS, get_type_priority
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

logger = logging.getLogger(__name__)

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
        
        access_token = data.get("access_token")
        if not access_token:
             raise ValueError("Failed to retrieve Spotify access token")
             
        self._access_token = access_token
        # Set expiration (subtract 60s for safety)
        self._token_expires_at = time.time() + data["expires_in"] - 60
        
        return access_token

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        # Only retry on transient server errors (5xx, 429). Never retry 4xx client errors.
        retry=retry_if_exception(
            lambda e: isinstance(e, httpx.HTTPStatusError)
                      and (e.response.status_code == 429 or e.response.status_code >= 500)
        ),
        reraise=True,
    )
    async def _get_request(
        active_client: httpx.AsyncClient, 
        token: str, 
        base_url: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Actual HTTP GET request with retry logic."""
        response = await active_client.get(
            f"{base_url}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params
        )
        response.raise_for_status()
        return response.json()

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """Authenticated GET request with retry logic for rate limiting and transient errors."""
        active_client = client or await self.get_client()
        token = await self._get_access_token(active_client)
        
        return await self._get_request(active_client, token, self.base_url, endpoint, params)

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
        # We fetch more than 50 to ensure we don't miss EPs for prolific artists
        params = {
            "include_groups": "album,single,compilation", 
            "limit": 50,
            "market": "US"
        }
        
        all_items = []
        url = f"/artists/{artist_id}/albums"
        
        # Fetch up to 2 pages (100 items) to balance speed and completeness
        for _ in range(2):
            res = await self._get(url, params=params if not all_items else None, client=client)
            items = res.get("items", [])
            all_items.extend(items)
            
            next_url = res.get("next")
            if not next_url:
                break
            url = next_url.replace(self.base_url, "")
        
        # Deduplicate and Clean
        return self._process_albums(all_items, artist_name)

    async def search_artists_only(self, query: str, client: Optional[httpx.AsyncClient] = None) -> List[str]:
        """Search for artist names only (lightweight)."""
        search_res = await self._get("/search", params={"q": query, "type": "artist", "limit": 5}, client=client)
        items = search_res.get("artists", {}).get("items", [])
        return [artist["name"] for artist in items]

    def _process_albums(self, albums: List[Dict[str, Any]], artist_name: str) -> List[Dict[str, Any]]:
        """Deduplicate albums (Spotify returns many versions) and format."""
        deduped = {}
        
        for album in albums:
            title = album.get("name", "")
            if not title:
                continue
            
            # Skip noise
            if any(kw in title.lower() for kw in SKIP_KEYWORDS):
                continue
            
            # Normalize title
            norm_title = normalize_title(title)
            is_deluxe = any(kw in title.lower() for kw in DELUXE_KEYWORDS)
            
            # Determine type label and priority
            raw_type = album.get("album_type", "").lower()
            total_tracks = album.get("total_tracks", 0)
            
            # Label as EP if:
            # 1. Spotify explicitly says "ep" (rare but possible)
            # 2. It's a "single" but has 4-7 tracks (Spotify's "single" limit is often fuzzy)
            # 3. It's an "album" but has 4-7 tracks (Many EPs are uploaded as albums)
            # 4. The title contains "EP"
            is_ep_in_title = any(pattern in title.lower() for pattern in [" - ep", " ep", "(ep)"])
            
            if raw_type == "ep" or (4 <= total_tracks <= 7) or is_ep_in_title:
                display_type = "EP"
            else:
                display_type = raw_type.capitalize()
            
            priority = get_type_priority(display_type)
            
            # Key collision logic
            if norm_title not in deduped:
                deduped[norm_title] = (album, display_type, priority, is_deluxe)
            else:
                existing_album, existing_display, existing_priority, existing_is_deluxe = deduped[norm_title]
                
                replace = False
                if priority < existing_priority:
                    replace = True
                elif priority == existing_priority:
                    if is_deluxe and not existing_is_deluxe:
                        replace = True
                    elif is_deluxe == existing_is_deluxe:
                        if total_tracks > existing_album.get("total_tracks", 0):
                            replace = True
                
                if replace:
                    deduped[norm_title] = (album, display_type, priority, is_deluxe)

        results = []
        for album, display_type, _, _ in deduped.values():
            results.append({
                "id": album["id"],
                "title": album["name"],
                "artist": album["artists"][0]["name"] if album["artists"] else artist_name,
                "type": display_type,
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

    async def get_playlist_tracks(self, playlist_id: str, limit: int = 100, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        """Fetch tracks from a public Spotify playlist with fallback for curated playlists."""
        all_tracks = []
        url = f"/playlists/{playlist_id}/tracks"
        params = {
            "fields": "items(track(name,external_ids,popularity,artists(name),duration_ms,album(images),id)),total,next",
            "limit": 100, 
            "market": "US"
        }
        
        try:
            while url and len(all_tracks) < limit:
                if url.startswith(self.base_url):
                    endpoint = url.replace(self.base_url, "")
                else:
                    endpoint = url
                    
                data = await self._get(endpoint, params=params if not all_tracks else None, client=client)
                items = data.get("items", [])
                
                for item in items:
                    track = item.get("track")
                    if not track: continue
                    if not track.get("name") or not track.get("artists"): continue
                    
                    all_tracks.append({
                        "name": track["name"],
                        "artist": track["artists"][0]["name"],
                        "isrc": track.get("external_ids", {}).get("isrc"),
                        "popularity": track.get("popularity", 0),
                        "duration_ms": track.get("duration_ms", 0),
                        "cover_url": track["album"]["images"][0]["url"] if track.get("album", {}).get("images") else None,
                        "spotify_id": track.get("id"),
                        "genres": []
                    })
                    if len(all_tracks) >= limit: break
                url = data.get("next")
            return all_tracks

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(f"Standard API 404 for playlist {playlist_id}. Attempting embed fallback.")
                return await self._fetch_tracks_from_embed(playlist_id, limit=limit, client=client)
            raise

    async def _fetch_tracks_from_embed(self, playlist_id: str, limit: int = 100, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        """Scrape track IDs from the Spotify embed page and fetch details in bulk."""
        active_client = client or await self.get_client()
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        
        try:
            resp = await active_client.get(embed_url)
            resp.raise_for_status()
            
            # Extract JSON blob from the script tag
            # Pattern matches the large props object in the embed HTML
            match = re.search(r'\{"props":.*\}', resp.text)
            if not match:
                logger.error(f"Could not find JSON data in embed page for {playlist_id}")
                return []
                
            data = json.loads(match.group(0))
            entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            track_list = entity.get("trackList", [])
            
            if not track_list:
                logger.warning(f"No tracks found in embed JSON for {playlist_id}")
                return []
                
            logger.info(f"Scraper found playlist '{entity.get('name')}' with {len(track_list)} tracks.")
                
            # Extract track IDs (limit to requested amount)
            track_ids = []
            for item in track_list[:limit]:
                uri = item.get("uri", "")
                if "spotify:track:" in uri:
                    track_ids.append(uri.split(":")[-1])
            
            if not track_ids:
                return []
                
            # Fetch full details in bulk (Track API still works with Client Credentials!)
            return await self._get_bulk_tracks(track_ids, client=active_client)
            
        except Exception as e:
            logger.error(f"Embed fallback failed for {playlist_id}: {e}")
            return []

    async def _get_bulk_tracks(self, track_ids: List[str], client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Fetch track details in batches of 50 using the /tracks API."""
        all_details = []
        for i in range(0, len(track_ids), 50):
            batch = track_ids[i:i+50]
            ids_str = ",".join(batch)
            try:
                data = await self._get("/tracks", params={"ids": ids_str, "market": "US"}, client=client)
                tracks = data.get("tracks", [])
                for track in tracks:
                    if not track: continue
                    all_details.append({
                        "name": track["name"],
                        "artist": track["artists"][0]["name"],
                        "isrc": track.get("external_ids", {}).get("isrc"),
                        "popularity": track.get("popularity", 0),
                        "duration_ms": track.get("duration_ms", 0),
                        "cover_url": track["album"]["images"][0]["url"] if track.get("album", {}).get("images") else None,
                        "spotify_id": track.get("id"),
                        "genres": []
                    })
            except Exception as e:
                logger.error(f"Error fetching bulk tracks: {e}")
                
        return all_details

    async def get_playlist_metadata(self, playlist_id: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """Fetch playlist metadata (name, owner, images) with fallbacks."""
        try:
            data = await self._get(f"/playlists/{playlist_id}", params={"fields": "name,owner,images"}, client=client)
            return {
                "name": data.get("name"),
                "owner": data.get("owner", {}).get("display_name"),
                "image_url": data.get("images", [{}])[0].get("url") if data.get("images") else None
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(f"Metadata API 404 for {playlist_id}. Attempting scraper fallback.")
                # Try Embed Scraper first for rich metadata
                embed_metadata = await self._fetch_metadata_from_embed(playlist_id, client=client)
                if embed_metadata and embed_metadata.get("name") and embed_metadata.get("name") != "Unknown Playlist":
                    return embed_metadata
                
                # Fallback to oEmbed if scraper fails
                return await self._fetch_metadata_from_oembed(playlist_id, client=client)
            raise

    async def _fetch_metadata_from_embed(self, playlist_id: str, client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
        """Extract playlist metadata from the embed page HTML/JSON."""
        active_client = client or await self.get_client()
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        
        try:
            resp = await active_client.get(embed_url)
            resp.raise_for_status()
            
            match = re.search(r'\{"props":.*\}', resp.text)
            if not match: return None
                
            data = json.loads(match.group(0))
            entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
            
            if not entity: return None
            
            # Extract image from visualIdentity or coverArt
            image_url = None
            viz_images = entity.get("visualIdentity", {}).get("image", [])
            if viz_images:
                # Pick largest
                image_url = viz_images[-1].get("url")
            elif entity.get("coverArt", {}).get("sources"):
                image_url = entity["coverArt"]["sources"][0].get("url")
                
            return {
                "name": entity.get("name") or entity.get("title"),
                "owner": entity.get("subtitle") or "Spotify",
                "image_url": image_url
            }
        except Exception as e:
            logger.error(f"Embed metadata fallback failed for {playlist_id}: {e}")
            return None

    async def _fetch_metadata_from_oembed(self, playlist_id: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """Use oEmbed API as a metadata fallback for curated playlists."""
        active_client = client or await self.get_client()
        url = "https://open.spotify.com/oembed"
        params = {"url": f"https://open.spotify.com/playlist/{playlist_id}"}
        
        try:
            resp = await active_client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return {
                "name": data.get("title"),
                "owner": "Spotify", # Curated playlists are owned by Spotify
                "image_url": data.get("thumbnail_url")
            }
        except Exception as e:
            logger.error(f"oEmbed fallback failed for {playlist_id}: {e}")
            return {"name": "Unknown Playlist", "owner": "Spotify", "image_url": None}

    def _clean_tracks(self, tracks: List[Dict[str, Any]]) -> List[str]:
        cleaned = []
        seen = set()
        
        for t in tracks:
            name = t.get("name", "")
            if not name:
                continue
            
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
