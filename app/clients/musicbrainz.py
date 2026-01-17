import httpx
import re
import asyncio
import time
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.core.utils import normalize_title, DELUXE_KEYWORDS, SKIP_KEYWORDS, get_type_priority

class MusicBrainzClient:
    def __init__(self):
        self.base_url = "https://musicbrainz.org/ws/2"
        self.headers = {
            "User-Agent": settings.MUSICBRAINZ_USER_AGENT,
            "Accept": "application/json",
        }
        self._client = None
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._min_interval = 1.1  # MusicBrainz allows 1 req/s; 1.1s is safer

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(30.0),
                follow_redirects=True
            )
        return self._client

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        async with self._lock:
            # Calculate wait time
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            
            # Use provided client or internal one
            active_client = client or await self.get_client()
            
            # MusicBrainz prefers fmt=json in params
            params = params or {}
            params["fmt"] = "json"
            
            try:
                response = await active_client.get(
                    f"{self.base_url}{endpoint}", 
                    params=params
                )
                self._last_call = time.time()
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 503:
                    # If we still hit a 503, wait longer next time
                    self._last_call = time.time() + 2.0 
                raise

    async def search_artist(self, query: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        data = await self._get("/artist", params={"query": query}, client=client)
        return data.get("artists", [])

    async def search_release_group(self, artist_name: str, album_name: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
        """
        Search for a specific release group by artist and title.
        Returns the first matching MBID or None.
        """
        query = f'artist:"{artist_name}" AND releasegroup:"{album_name}"'
        data = await self._get("/release-group", params={"query": query}, client=client)
        rgs = data.get("release-groups") or []
        if rgs:
            return rgs[0].get("id")
        return None

    async def get_artist_release_groups(self, artist_id: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
        # Release Groups are the "logical" albums. 
        # This is one query and much faster than paging through all releases.
        params = {
            "artist": artist_id,
            "limit": 100
        }
        data = await self._get("/release-group", params=params, client=client)
        release_groups = data.get("release-groups") or []
        
        # Deduplication and Deluxe Prioritization
        deduplicated = {}
        for rg in release_groups:
            title = rg.get("title") or ""
            title_lower = title.lower()
            
            # Explicitly skip junk album types from search results
            if any(kw in title_lower for kw in SKIP_KEYWORDS):
                continue
                
            # Also check secondary types for explicit remix/live/demo tags
            secondary_types = [t.lower() for t in (rg.get("secondary-types") or [])]
            if any(kw in secondary_types for kw in ["remix", "live", "demo"]):
                continue
                
            norm_title = normalize_title(title)
            
            if not norm_title:
                norm_title = re.sub(r'[^a-z0-9]', '', title.lower()).strip()
            
            rg_type = rg.get("primary-type") or "Other"
            is_deluxe = any(kw in title.lower() for kw in DELUXE_KEYWORDS)
            
            if norm_title not in deduplicated:
                deduplicated[norm_title] = rg
            else:
                existing = deduplicated[norm_title]
                existing_title = existing.get("title") or ""
                existing_type = existing.get("primary-type") or "Other"
                existing_is_deluxe = any(kw in existing_title.lower() for kw in DELUXE_KEYWORDS)
                
                # Selection Logic:
                # 1. Prefer Album > EP > Single
                # 2. If same type, prefer Deluxe over standard
                # 3. If same type and deluxe status, prefer longer title
                
                new_priority = get_type_priority(rg_type)
                old_priority = get_type_priority(existing_type)
                
                replace = False
                if new_priority < old_priority:
                    replace = True
                elif new_priority == old_priority:
                    if is_deluxe and not existing_is_deluxe:
                        replace = True
                    elif is_deluxe == existing_is_deluxe:
                        if len(title) > len(existing_title):
                            replace = True
                
                if replace:
                    deduplicated[norm_title] = rg

        results = []
        for rg in deduplicated.values():
            results.append({
                "id": rg.get("id"),
                "title": rg.get("title"),
                "type": rg.get("primary-type") or "Other",
                "cover_art": rg.get("cover-art-archive") or {}
            })
            
        return sorted(results, key=lambda x: (get_type_priority(x["type"]), x["title"] or ""))

    async def get_release_group_info(self, rg_id: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
        """Resolve a Release Group MBID to Artist and Title."""
        data = await self._get(f"/release-group/{rg_id}", params={"inc": "artists"}, client=client)
        return {
            "title": data.get("title"),
            "artist": data.get("artist-credit", [{}])[0].get("artist", {}).get("name")
        }

    def _parse_tracks(self, release_data: Dict[str, Any], release_title: str) -> List[str]:
        raw_tracks = []
        for medium in (release_data.get("media") or []):
            for track in (medium.get("tracks") or []):
                raw_tracks.append(track.get("title") or "")

        # 2. Cleanup and Deduplicate logic
        # Keywords that indicate we should probably skip the track for a standard ranking
        is_remix_album = "remix" in release_title.lower()
        is_live_album = "live" in release_title.lower()
        
        # Base skip list
        skip_keywords = ["instrumental", "karaoke", "voice memo", "commentary", "acappella", "orchestral"]
        
        # If it's not a dedicated remix album, skip remix-related tracks
        if not is_remix_album:
            skip_keywords.extend(["remix", "mix", "refix", "edit", "rework"])
            
        if not is_live_album:
            skip_keywords.extend(["live from", "(live)", "[live]"])
            
        cleaned_tracks = []
        seen_base_titles = {} # Use dict to store (base_title: original_title)
        
        for track in raw_tracks:
            if not track:
                continue
            track_lower = track.lower()
            
            # Skip placeholders
            if track_lower in ["[untitled]", "untitled", "[unknown]", "unknown"]:
                continue
                
            # Simple skip check
            should_skip = False
            
            # Explicit check for "karaoke" anywhere in the name as requested
            if "karaoke" in track_lower:
                should_skip = True
            
            if not should_skip:
                for kw in skip_keywords:
                    # Check for word boundaries. We use a simpler check for common patterns.
                    if re.search(rf"\b{re.escape(kw)}\b", track_lower):
                        # Special Case: "Mix" can be part of a real title (e.g., "The Mix")
                        # but if it's in parentheses or after a hyphen, it's almost certainly a remix tag.
                        if kw == "mix":
                            if any(p in track_lower for p in ["(mix", "[mix", " - mix", " remix"]):
                                should_skip = True
                                break
                        else:
                            should_skip = True
                            break
            
            if should_skip:
                continue
                
            # Normalize title for deduplication
            # 1. Remove parentheticals and brackets
            base_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', track_lower)
            # 2. Remove anything after a hyphen
            base_title = re.sub(r' - .*', '', base_title)
            # 3. Final cleanup - keep alphanumeric including Unicode letters
            base_title = re.sub(r'[^\w]', '', base_title).strip()
            
            if not base_title:
                continue
                
            # For deluxe albums, we want to keep "Extended" or "Remix" versions if they are distinct
            is_distinct_version = any(kw in track_lower for kw in ["extended", "remix", "feat", "with "])
            
            dedup_key = base_title
            if is_distinct_version:
                # Add a bit of the original title to the key to keep it distinct
                dedup_key = f"{base_title}_{track_lower}"

            if dedup_key not in seen_base_titles:
                cleaned_tracks.append(track)
                seen_base_titles[dedup_key] = track
            else:
                # Keep the shortest title version (usually the cleanest base name)
                existing_track = seen_base_titles[dedup_key]
                if len(track) < len(existing_track):
                    try:
                        idx = cleaned_tracks.index(existing_track)
                        cleaned_tracks[idx] = track
                        seen_base_titles[dedup_key] = track
                    except ValueError:
                        pass
        
        return cleaned_tracks

    def _score_release(self, release: Dict[str, Any], english_countries: List[str], completeness_keywords: List[str]) -> int:
        """Calculate a quality score for a release to pick the best version."""
        total_tracks = sum((medium.get("track-count") or 0) for medium in (release.get("media") or []))
        title = release.get("title") or ""
        title_lower = title.lower()
        country = release.get("country") or ""
        
        score = 0
        
        # 1. Geographic Priority (Strong)
        if country in english_countries:
            score += 100
        elif not country: # International/Unknown is better than specific non-English
            score += 50
            
        # 2. Script/Language check (Strong)
        # Favor titles that don't have non-ASCII characters (Japanese, Cyrillic, etc.)
        if not re.search(r'[^\x00-\x7F]', title):
            score += 200
        
        # 3. Completeness (Medium)
        if any(kw in title_lower for kw in completeness_keywords):
            score += 50
            
        # 4. Tie-breaker: Track count (Small)
        score += (total_tracks * 2)
        
        return score

    async def get_release_group_tracks(self, rg_id: str, client: Optional[httpx.AsyncClient] = None) -> List[str]:
        # To get tracks, we first try to treat rg_id as a Release Group ID
        statuses = ["official", None]
        releases = []
        
        try:
            release_data = await self._get(f"/release/{rg_id}", params={"inc": "recordings"}, client=client)
            if "media" in release_data:
                return self._parse_tracks(release_data, release_data.get("title", ""))
        except Exception:
            pass

        for status in statuses:
            params = {"release-group": rg_id, "inc": "media", "limit": 100}
            if status:
                params["status"] = status
            try:
                data = await self._get("/release", params=params, client=client)
                releases = data.get("releases") or []
                if releases:
                    break
            except Exception:
                continue
        
        if not releases:
            return []
            
        completeness_keywords = [
            "deluxe", "expanded", "paradise", "edition", "complete", 
            "remastered", "3am", "til dawn", "platinum", "gold", "diamond",
            "special", "collector", "limited", "super", "ultra", "ultimate"
        ]
        english_countries = ["US", "GB", "UK", "CA", "AU", "NZ", "XE", "XW"]

        # Scoring system to pick the best release
        best_release = releases[0]
        best_score = -1000
        
        for release in releases:
            score = self._score_release(release, english_countries, completeness_keywords)
            total_tracks = sum((medium.get("track-count") or 0) for medium in (release.get("media") or []))
            
            if score > best_score:
                best_score = score
                best_release = release
            elif score == best_score:
                # Tie-breaker on track count if scores are identical
                best_total = sum((medium.get("track-count") or 0) for medium in (best_release.get("media") or []))
                if total_tracks > best_total:
                    best_release = release

        release_data = await self._get(f"/release/{best_release['id']}", params={"inc": "recordings"}, client=client)
        return self._parse_tracks(release_data, best_release.get("title", ""))

musicbrainz_client = MusicBrainzClient()
