import httpx
from typing import List, Dict, Any, Optional
from app.core.config import settings

class LastFMClient:
    def __init__(self):
        self.base_url = "http://ws.audioscrobbler.com/2.0/"
        self.api_key = settings.LASTFM_API_KEY
        self.headers = {
            "User-Agent": settings.MUSICBRAINZ_USER_AGENT, # Reuse or create specific one
        }
        self._client = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(20.0),
                follow_redirects=True
            )
        return self._client

    async def _get(self, method: str, params: Optional[Dict[str, Any]] = None, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        active_client = client or await self.get_client()
        params = params or {}
        params["method"] = method
        params["api_key"] = self.api_key
        params["format"] = "json"
        
        response = await active_client.get(self.base_url, params=params)
        response.raise_for_status()
        return response.json()

    async def search_artist(self, query: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        """
        Search for an artist by name.
        Returns a list of artist objects with name, mbid, and images.
        """
        data = await self._get("artist.search", params={"artist": query, "limit": 10}, client=client)
        results = data.get("results", {})
        artist_matches = results.get("artistmatches", {})
        artists = artist_matches.get("artist", [])
        
        # Standardize for our app
        return [{
            "id": a.get("mbid") or a.get("name"), # Fallback to name if mbid missing
            "name": a.get("name"),
            "mbid": a.get("mbid"),
            "url": a.get("url")
        } for a in artists]

    async def get_artist_top_albums(self, artist_name: str, limit: int = 30, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        """
        Get top albums for an artist, ordered by popularity/playcount.
        """
        data = await self._get("artist.gettopalbums", params={"artist": artist_name, "limit": limit}, client=client)
        top_albums = data.get("topalbums", {})
        albums = top_albums.get("album", [])
        
        results = []
        for album in albums:
            # Last.fm provides images in different sizes
            images = album.get("image") or []
            cover_art_url = ""
            for img in images:
                if img.get("size") == "extralarge" or img.get("size") == "large":
                    cover_art_url = img.get("#text")
            
            results.append({
                "id": album.get("mbid"),
                "title": album.get("name"),
                "artist": album.get("artist", {}).get("name"),
                "mbid": album.get("mbid"),
                "image_url": cover_art_url,
                "playcount": album.get("playcount")
            })
        return results

    async def get_album_info(self, artist_name: Optional[str] = None, album_name: Optional[str] = None, mbid: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """
        Get detailed album info including the tracklist.
        Can be called with (artist, album) or (mbid).
        """
        params = {}
        if mbid:
            params["mbid"] = mbid
        elif artist_name and album_name:
            params["artist"] = artist_name
            params["album"] = album_name
        else:
            raise ValueError("Must provide mbid or artist_name and album_name")
            
        data = await self._get("album.getinfo", params=params, client=client)
        return data.get("album", {})

    async def get_album_tracks(self, album_id: str, client: Optional[httpx.AsyncClient] = None) -> List[str]:
        """
        Fetch track titles for a specific album using its MBID or custom "artist:album" ID.
        """
        album_info = None
        if ":" in album_id: # Likely our custom format "Artist:Album"
            try:
                artist, album = album_id.split(":", 1)
                album_info = await self.get_album_info(artist_name=artist, album_name=album, client=client)
            except ValueError:
                # If split fails or something else, try as MBID
                album_info = await self.get_album_info(mbid=album_id, client=client)
        else:
            album_info = await self.get_album_info(mbid=album_id, client=client)
            
        if not album_info or not isinstance(album_info, dict):
            return []

        tracks_data = album_info.get("tracks", {}).get("track", []) if album_info.get("tracks") else []
        
        # Filter out placeholders and check for quality
        results = []
        placeholder_count = 0
        placeholders = {"[untitled]", "untitled", "[unknown]", "unknown", "untitled track"}
        
        for t in tracks_data:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name", "")).strip()
            if not name:
                continue
            
            if name.lower() in placeholders or "untitled track" in name.lower():
                placeholder_count += 1
                continue
                
            results.append(name)
            
        # If more than 2 tracks were placeholders, or more than 20% of the list, 
        # it's better to fallback to MusicBrainz.
        if placeholder_count > 0:
            total = len(results) + placeholder_count
            if placeholder_count > 2 or (total > 0 and placeholder_count / total > 0.2):
                return []
                
        return results

lastfm_client = LastFMClient()
