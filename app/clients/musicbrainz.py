import httpx
import re
from typing import List, Dict, Any, Optional
from app.core.config import settings

class MusicBrainzClient:
    def __init__(self):
        self.base_url = "https://musicbrainz.org/ws/2"
        self.headers = {
            "User-Agent": settings.MUSICBRAINZ_USER_AGENT,
            "Accept": "application/json",
        }
        self._client = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(30.0),
                follow_redirects=True
            )
        return self._client

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        client = await self.get_client()
        # MusicBrainz prefers fmt=json in params
        params = params or {}
        params["fmt"] = "json"
        
        response = await client.get(
            f"{self.base_url}{endpoint}", 
            params=params
        )
        response.raise_for_status()
        return response.json()

    async def search_artist(self, query: str) -> List[Dict[str, Any]]:
        data = await self._get("/artist", params={"query": query})
        return data.get("artists", [])

    async def get_artist_release_groups(self, artist_id: str) -> List[Dict[str, Any]]:
        # Release Groups are the "logical" albums. 
        # This is one query and much faster than paging through all releases.
        params = {
            "artist": artist_id,
            "limit": 100
        }
        data = await self._get("/release-group", params=params)
        release_groups = data.get("release-groups") or []
        
        # Expanded list of deluxe-indicating keywords
        deluxe_keywords = [
            "deluxe", "expanded", "platinum", "special", "edition", 
            "complete", "remastered", "3am", "til dawn", "paradise",
            "gold", "diamond", "anniversary", "collector", "limited",
            "super", "ultra", "mega", "ultimate"
        ]

        def get_type_priority(rg_type):
            if rg_type == "Album": return 0
            if rg_type == "EP": return 1
            if rg_type == "Single": return 2
            return 3

        def normalize(title):
            if not title: return ""
            # Remove parenthetical info which often contains "Deluxe Edition"
            base = title.lower()
            base = re.sub(r'[\(\[\{].*?[\)\]\}]', '', base)
            # Remove non-alphanumeric
            return re.sub(r'[^a-z0-9]', '', base).strip()

        # Deduplication and Deluxe Prioritization
        deduplicated = {}
        for rg in release_groups:
            title = rg.get("title") or ""
            title_lower = title.lower()
            
            # Explicitly skip junk album types from search results
            skip_album_keywords = ["karaoke", "instrumental", "tour", "live", "sessions", "demos", "remixes", "remix"]
            if any(kw in title_lower for kw in skip_album_keywords):
                continue
                
            # Also check secondary types for explicit remix/live/demo tags
            secondary_types = [t.lower() for t in (rg.get("secondary-types") or [])]
            if any(kw in secondary_types for kw in ["remix", "live", "demo"]):
                continue
                
            norm_title = normalize(title)
            
            if not norm_title:
                norm_title = re.sub(r'[^a-z0-9]', '', title.lower()).strip()
            
            rg_type = rg.get("primary-type") or "Other"
            is_deluxe = any(kw in title.lower() for kw in deluxe_keywords)
            
            if norm_title not in deduplicated:
                deduplicated[norm_title] = rg
            else:
                existing = deduplicated[norm_title]
                existing_title = existing.get("title") or ""
                existing_type = existing.get("primary-type") or "Other"
                existing_is_deluxe = any(kw in existing_title.lower() for kw in deluxe_keywords)
                
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

    async def get_release_group_tracks(self, rg_id: str) -> List[str]:
        # To get tracks for a release group, we first fetch all official releases in that group
        params = {
            "release-group": rg_id,
            "inc": "media",
            "status": "official",
            "limit": 100
        }
        data = await self._get("/release", params=params)
        releases = data.get("releases") or []
        
        if not releases:
            return []
            
        completeness_keywords = [
            "deluxe", "expanded", "paradise", "edition", "complete", 
            "remastered", "3am", "til dawn", "platinum", "gold", "diamond",
            "special", "collector", "limited", "super", "ultra", "ultimate"
        ]
        
        # English-speaking or international territories
        english_countries = ["US", "GB", "UK", "CA", "AU", "NZ", "XE", "XW"]

        # Scoring system to pick the best release
        best_release_id = releases[0].get("id")
        best_score = -1000
        best_track_count = 0
        best_release_title = releases[0].get("title") or ""
        
        for release in releases:
            total_tracks = sum((medium.get("track-count") or 0) for medium in (release.get("media") or []))
            title = release.get("title") or ""
            title_lower = title.lower()
            country = release.get("country") or ""
            
            # Start with a base score
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
            # We want the deluxe version WITHIN our preferred language/country
            score += (total_tracks * 2)

            if score > best_score:
                best_score = score
                best_track_count = total_tracks
                best_release_id = release.get("id")
                best_release_title = title
            elif score == best_score and total_tracks > best_track_count:
                best_track_count = total_tracks
                best_release_id = release.get("id")
                best_release_title = title

        # Now do a single lookup for the best scored release to get all track titles
        release_data = await self._get(f"/release/{best_release_id}", params={"inc": "recordings"})
        
        raw_tracks = []
        for medium in (release_data.get("media") or []):
            for track in (medium.get("tracks") or []):
                raw_tracks.append(track.get("title") or "")

        # 2. Cleanup and Deduplicate logic
        # Keywords that indicate we should probably skip the track for a standard ranking
        is_remix_album = "remix" in best_release_title.lower()
        is_live_album = "live" in best_release_title.lower()
        
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
            if not track: continue
            track_lower = track.lower()
            
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
                
            if base_title not in seen_base_titles:
                cleaned_tracks.append(track)
                seen_base_titles[base_title] = track
            else:
                # Keep the shortest title version (usually the cleanest base name)
                existing_track = seen_base_titles[base_title]
                if len(track) < len(existing_track):
                    try:
                        idx = cleaned_tracks.index(existing_track)
                        cleaned_tracks[idx] = track
                        seen_base_titles[base_title] = track
                    except ValueError:
                        pass
        
        return cleaned_tracks

musicbrainz_client = MusicBrainzClient()

