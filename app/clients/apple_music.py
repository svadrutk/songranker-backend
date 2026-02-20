import base64
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
import jwt
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.utils import DELUXE_KEYWORDS, SKIP_KEYWORDS, normalize_title, get_type_priority

logger = logging.getLogger(__name__)

_TOKEN_LIFETIME = 86400      # 24 hours
_TOKEN_REFRESH_BUFFER = 300  # Regenerate 5 min before expiry


class AppleMusicClient:
    BASE_URL = "https://api.music.apple.com/v1"

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
            )
        return self._client

    # ------------------------------------------------------------------
    # JWT auth
    # ------------------------------------------------------------------

    def _generate_jwt(self) -> str:
        """Return a cached ES256 developer token; rotate every 24 hours."""
        if self._token and time.time() < (self._token_expires_at - _TOKEN_REFRESH_BUFFER):
            return self._token

        raw_key = base64.b64decode(settings.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value())
        private_key_pem = raw_key.decode("utf-8")

        now = int(time.time())
        token = jwt.encode(
            {
                "iss": settings.APPLE_MUSIC_TEAM_ID,
                "iat": now,
                "exp": now + _TOKEN_LIFETIME,
            },
            private_key_pem,
            algorithm="ES256",
            headers={"kid": settings.APPLE_MUSIC_KEY_ID},
        )
        # PyJWT 2.x always returns str
        self._token = token
        self._token_expires_at = now + _TOKEN_LIFETIME
        logger.info("Apple Music JWT generated (expires in 24h)")
        return self._token

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        # Retry: 429 (rate limit), 404 (Apple transient infra bug), 5xx (server errors)
        # Never retry: 400 (our bug), 401 (bad JWT — config error), 403 (private/unauthorized)
        retry=retry_if_exception(
            lambda e: isinstance(e, httpx.HTTPStatusError)
            and (
                e.response.status_code == 429
                or e.response.status_code == 404
                or e.response.status_code >= 500
            )
        ),
        reraise=True,
    )
    async def _get_request(
        active_client: httpx.AsyncClient,
        token: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = await active_client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        active_client = client or await self.get_client()
        token = self._generate_jwt()
        if path.startswith("http"):
            url = path
        elif path.startswith("/v1"):
            url = f"https://api.music.apple.com{path}"
        else:
            url = f"{self.BASE_URL}{path}"
        return await self._get_request(active_client, token, url, params)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_artist_albums(
        self,
        artist_name: str,
        storefront: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """Two-step: find artist ID → fetch all albums (up to 4 pages = 100 albums).

        Mirrors SpotifyClient.search_artist_albums for completeness on prolific artists.
        """
        sf = storefront or settings.APPLE_MUSIC_STOREFRONT

        # Step 1: artist ID lookup
        search_data = await self._get(
            f"/catalog/{sf}/search",
            params={"term": artist_name, "types": "artists", "limit": 1},
            client=client,
        )
        artists = search_data.get("results", {}).get("artists", {}).get("data", [])
        if not artists:
            return []

        artist_id = artists[0]["id"]

        # Step 2: fetch albums paginated (up to 4 pages × 25 = 100)
        all_albums: List[Dict[str, Any]] = []
        url = f"/catalog/{sf}/artists/{artist_id}/albums"
        params: Optional[Dict[str, Any]] = {"limit": 25}

        for _ in range(4):
            data = await self._get(url, params=params, client=client)
            items = data.get("data", [])
            all_albums.extend(items)
            next_path = data.get("next")
            if not next_path:
                break
            if next_path.startswith("http"):
                url = next_path
            elif next_path.startswith("/v1"):
                url = f"https://api.music.apple.com{next_path}"
            else:
                url = f"{self.BASE_URL}{next_path}"
            params = None  # offset already embedded in next URL

        return self._process_albums(all_albums, artist_name)

    async def search_artists_only(
        self,
        query: str,
        storefront: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[str]:
        """Lightweight artist name search (for autocomplete suggestions)."""
        sf = storefront or settings.APPLE_MUSIC_STOREFRONT
        data = await self._get(
            f"/catalog/{sf}/search",
            params={"term": query, "types": "artists", "limit": 5},
            client=client,
        )
        items = data.get("results", {}).get("artists", {}).get("data", [])
        return [item["attributes"]["name"] for item in items if item.get("attributes", {}).get("name")]

    # ------------------------------------------------------------------
    # Album tracks
    # ------------------------------------------------------------------

    async def get_album_tracks(
        self,
        album_id: str,
        storefront: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[str]:
        """Fetch clean tracklist for an Apple Music album ID."""
        sf = storefront or settings.APPLE_MUSIC_STOREFRONT
        # include=tracks fetches first page inline; paginate if album has >100 tracks
        data = await self._get(
            f"/catalog/{sf}/albums/{album_id}",
            params={"include": "tracks"},
            client=client,
        )
        albums = data.get("data", [])
        if not albums:
            return []

        tracks_rel = albums[0].get("relationships", {}).get("tracks", {})
        all_tracks = list(tracks_rel.get("data", []))

        # Paginate if >100 tracks (rare — compilation albums)
        next_path = tracks_rel.get("next")
        while next_path:
            page = await self._get(next_path, client=client)
            all_tracks.extend(page.get("data", []))
            next_path = page.get("next")

        return self._clean_tracks(all_tracks)

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------

    async def get_playlist_metadata(
        self,
        playlist_id: str,
        storefront: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Fetch playlist name, curator, and cover image."""
        data = await self._get(
            f"/catalog/{storefront}/playlists/{playlist_id}",
            client=client,
        )
        items = data.get("data", [])
        if not items:
            return {"name": None, "curator": None, "image_url": None}

        attrs = items[0].get("attributes", {})
        artwork = attrs.get("artwork") or {}
        return {
            "name": attrs.get("name"),
            "curator": attrs.get("curatorName"),
            "image_url": self._resolve_artwork(artwork, size=500),
        }

    async def get_playlist_tracks(
        self,
        playlist_id: str,
        storefront: str,
        limit: int = 250,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch all tracks from a public Apple Music playlist.

        Uses the dedicated /tracks sub-endpoint (not ?include=tracks) which
        supports full pagination beyond 100 tracks — confirmed correct by Apple staff.
        """
        all_tracks: List[Dict[str, Any]] = []
        url = f"{self.BASE_URL}/catalog/{storefront}/playlists/{playlist_id}/tracks"
        params: Optional[Dict[str, Any]] = {"limit": 100}

        while url and len(all_tracks) < limit:
            data = await self._get(url, params=params, client=client)
            items = data.get("data", [])

            for idx, t in enumerate(items):
                # Only process songs — music videos have no ISRC
                if t.get("type") != "songs":
                    logger.debug(f"Skipping non-song track type={t.get('type')!r}")
                    continue

                attrs = t.get("attributes", {})
                artwork = attrs.get("artwork") or {}
                all_tracks.append({
                    "name": attrs.get("name"),
                    "artist": attrs.get("artistName"),
                    "album": attrs.get("albumName"),
                    "isrc": attrs.get("isrc"),
                    "duration_ms": attrs.get("durationInMillis", 0),
                    "cover_url": self._resolve_artwork(artwork, size=300),
                    "apple_music_id": t.get("id"),
                    "spotify_id": None,
                    "genres": attrs.get("genreNames", []),
                    # Use track position as popularity proxy (earlier = more prominent)
                    "popularity": len(all_tracks) + idx,
                })

                if len(all_tracks) >= limit:
                    break

            next_path = data.get("next")
            if next_path:
                if next_path.startswith("http"):
                    url = next_path
                elif next_path.startswith("/v1"):
                    url = f"https://api.music.apple.com{next_path}"
                else:
                    url = f"{self.BASE_URL}{next_path}"
            else:
                url = None
            params = None  # offset embedded in next URL

        return all_tracks

    # ------------------------------------------------------------------
    # Processing helpers
    # ------------------------------------------------------------------

    def _process_albums(
        self, albums: List[Dict[str, Any]], artist_name: str
    ) -> List[Dict[str, Any]]:
        """Deduplicate and format albums into ReleaseGroupResponse shape."""
        deduped: Dict[str, tuple] = {}

        for album in albums:
            attrs = album.get("attributes", {})
            title = attrs.get("name", "")
            if not title:
                continue

            if any(kw in title.lower() for kw in SKIP_KEYWORDS):
                continue

            norm_title = normalize_title(title)
            is_deluxe = any(kw in title.lower() for kw in DELUXE_KEYWORDS)
            display_type = self._get_release_type(attrs)
            priority = get_type_priority(display_type)
            total_tracks = attrs.get("trackCount", 0)

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
                        if total_tracks > existing_album.get("attributes", {}).get("trackCount", 0):
                            replace = True
                if replace:
                    deduped[norm_title] = (album, display_type, priority, is_deluxe)

        results = []
        for album, display_type, _, _ in deduped.values():
            attrs = album.get("attributes", {})
            artwork = attrs.get("artwork") or {}
            results.append({
                "id": album["id"],
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", artist_name),
                "type": display_type,
                "cover_art": {
                    "front": True,
                    "url": self._resolve_artwork(artwork, size=500),
                },
                "source": "apple_music",
            })

        return results

    @staticmethod
    def _get_release_type(attributes: Dict[str, Any]) -> str:
        # isCompilation MUST be checked first — a 12-track compilation would otherwise
        # be misclassified as "Album"
        if attributes.get("isCompilation", False):
            return "Compilation"

        track_count = attributes.get("trackCount", 0)
        is_single = attributes.get("isSingle", False)
        name = attributes.get("name", "").lower()

        # EP name tag takes priority over track-count-based single classification
        if " - ep" in name:
            return "EP"
        if is_single or track_count <= 3:
            return "Single"
        if track_count <= 6:
            return "EP"
        return "Album"

    @staticmethod
    def _resolve_artwork(artwork: Dict[str, Any], size: int = 500) -> Optional[str]:
        """Replace {w}x{h} template in Apple Music artwork URLs."""
        url = artwork.get("url")
        if not url:
            return None
        return url.replace("{w}", str(size)).replace("{h}", str(size))

    def _clean_tracks(self, tracks: List[Dict[str, Any]]) -> List[str]:
        """Return deduplicated track name list from raw song objects."""
        cleaned: List[str] = []
        seen: set = set()
        for t in tracks:
            attrs = t.get("attributes", {})
            name = attrs.get("name", "")
            if not name:
                continue
            lower = name.lower()
            if "commentary" in lower or "interview" in lower:
                continue
            if lower not in seen:
                cleaned.append(name)
                seen.add(lower)
        return cleaned


apple_music_client = AppleMusicClient()
