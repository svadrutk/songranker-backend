from typing import List, Optional, Dict, Any, cast
import httpx
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel
import asyncio
import re

from app.clients.musicbrainz import musicbrainz_client
from app.clients.lastfm import lastfm_client
from app.core.utils import normalize_title, DELUXE_KEYWORDS, SKIP_KEYWORDS
from app.core.cache import cache

router = APIRouter()

def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client

class CoverArtArchive(BaseModel):
    artwork: Optional[bool] = None
    back: Optional[bool] = None
    count: Optional[int] = None
    darkened: Optional[bool] = None
    front: Optional[bool] = None
    url: Optional[str] = None

class ReleaseGroupResponse(BaseModel):
    id: str
    title: str
    artist: Optional[str] = None
    type: Optional[str] = None
    cover_art: CoverArtArchive

class TrackResponse(BaseModel):
    tracks: List[str]

async def _get_artist_context(query: str, client: httpx.AsyncClient):
    """Retrieve artist name and MBID from Last.fm."""
    artists = await lastfm_client.search_artist(query, client=client)
    if not artists:
        return None
    # Return both for the cache
    return {"name": artists[0]["name"], "mbid": artists[0].get("mbid")}

async def _fetch_release_data(artist_name: str, artist_mbid: Optional[str], client: httpx.AsyncClient):
    """Gather release data from Last.fm and MusicBrainz in parallel."""
    if artist_mbid:
        mb_task = musicbrainz_client.get_artist_release_groups(artist_mbid, client=client)
    else:
        async def get_mb_groups_fallback():
            mb_artists = await musicbrainz_client.search_artist(artist_name, client=client)
            if mb_artists:
                return await musicbrainz_client.get_artist_release_groups(mb_artists[0]["id"], client=client)
            return []
        mb_task = get_mb_groups_fallback()

    lastfm_task = lastfm_client.get_artist_top_albums(artist_name, client=client)
    
    results = await asyncio.gather(lastfm_task, mb_task, return_exceptions=True)
    
    lastfm_res = cast(List[Dict[str, Any]], results[0] if not isinstance(results[0], Exception) else [])
    mb_res = cast(List[Dict[str, Any]], results[1] if not isinstance(results[1], Exception) else [])
    
    return _merge_results(lastfm_res, mb_res, artist_name)

def _merge_results(lastfm_albums: List[Dict], mb_release_groups: List[Dict], default_artist: str):
    """Merge and deduplicate results from both sources."""
    mb_lookup = {normalize_title(rg["title"]): rg for rg in mb_release_groups if normalize_title(rg["title"])}
    
    results_map = {}
    seen_mbids = set()

    for album in lastfm_albums:
        title = album["title"]
        if any(kw in title.lower() for kw in SKIP_KEYWORDS):
            continue

        norm_title = normalize_title(title)
        mb_entry = mb_lookup.get(norm_title)
        mbid = album["mbid"] or (mb_entry["id"] if mb_entry else None)
        
        if not mbid or mbid in seen_mbids:
            continue
        
        is_deluxe = any(kw in title.lower() for kw in DELUXE_KEYWORDS)
        new_entry = {
            "id": mbid,
            "title": title,
            "artist": album.get("artist") or default_artist,
            "type": mb_entry["type"] if mb_entry else "Album", 
            "cover_art": {
                "front": bool(album["image_url"]),
                "url": album["image_url"]
            }
        }

        if norm_title not in results_map:
            results_map[norm_title] = new_entry
            seen_mbids.add(mbid)
        else:
            existing = results_map[norm_title]
            existing_is_deluxe = any(kw in existing["title"].lower() for kw in DELUXE_KEYWORDS)
            
            if is_deluxe and not existing_is_deluxe:
                seen_mbids.remove(existing["id"])
                results_map[norm_title] = new_entry
                seen_mbids.add(mbid)
    
    return list(results_map.values())

@router.get("/search", response_model=List[ReleaseGroupResponse])
async def search(request: Request, background_tasks: BackgroundTasks, query: str = Query(..., min_length=1)):
    client = request.app.state.http_client
    
    # 1. Normalize query for typo/alias cache
    norm_query = re.sub(r'[^a-z0-9]', '', query.lower()).strip()
    if not norm_query:
        return []

    # 2. Get Artist Context (Alias Cache)
    # This handles "Taylow Swift" -> {"name": "Taylor Swift", "mbid": "..."}
    artist_context = await cache.get_or_fetch(
        f"alias:{norm_query}",
        lambda: _get_artist_context(query, client),
        ttl_seconds=86400 * 7, # Aliases (especially typos) are very stable
        background_tasks=background_tasks
    )

    if not artist_context:
        # Fallback to direct MB search if Last.fm fails
        return await _search_fallback(query, client)

    artist_name = artist_context["name"]
    artist_mbid = artist_context.get("mbid")

    # 3. Get Artist Albums (Canonical Cache)
    # Use MBID if available, else name
    cache_key = f"artist_albums:{artist_mbid or artist_name}"
    results = await cache.get_or_fetch(
        cache_key,
        lambda: _fetch_release_data(artist_name, artist_mbid, client),
        ttl_seconds=3600, # 1 hour
        background_tasks=background_tasks
    )

    return results

async def _search_fallback(query: str, client: httpx.AsyncClient):
    """Final fallback to pure MusicBrainz if context fails."""
    try:
        mb_artists = await musicbrainz_client.search_artist(query, client=client)
        if not mb_artists: 
            return []
        return await musicbrainz_client.get_artist_release_groups(mb_artists[0]["id"], client=client)
    except Exception:
        return []

@router.get("/tracks/{release_group_id}", response_model=TrackResponse)
async def get_tracks(
    request: Request, 
    background_tasks: BackgroundTasks, 
    release_group_id: str,
    artist: Optional[str] = Query(None),
    title: Optional[str] = Query(None)
):
    """Fetch track titles with a parallelized race strategy and intelligent merging."""
    client = request.app.state.http_client
    
    async def fetch_tracks():
        # Prepare parallel tasks
        tasks = []
        
        # Task 1: Last.fm by MBID
        tasks.append(lastfm_client.get_album_tracks(release_group_id, client=client))
        
        # Task 2: MusicBrainz (usually slower due to rate limiting)
        tasks.append(musicbrainz_client.get_release_group_tracks(release_group_id, client=client))
        
        # Task 3: If we have artist/title, try Last.fm by name immediately
        if artist and title:
            custom_id = f"{artist}:{title}"
            tasks.append(lastfm_client.get_album_tracks(custom_id, client=client))
        
        # Run all attempts in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = [r for r in results if isinstance(r, list) and len(r) > 0]
        
        if not valid_results and not (artist and title):
            # Final desperate attempt: Resolve name then try Last.fm
            try:
                info = await musicbrainz_client.get_release_group_info(release_group_id, client=client)
                if info.get("artist") and info.get("title"):
                    res = await lastfm_client.get_album_tracks(f"{info['artist']}:{info['title']}", client=client)
                    if res: return res
            except Exception:
                pass

        if not valid_results:
            return None

        # Intelligent Merging: Pick the "best" result
        # Best = most tracks (usually indicates a Deluxe/Complete version)
        # unless it's suspiciously large or looks like duplicates (already handled by clients)
        best_result = max(valid_results, key=len)
        return best_result

    tracks = await cache.get_or_fetch(
        f"tracks:{release_group_id}",
        fetch_tracks,
        ttl_seconds=86400, # 24 hours
        background_tasks=background_tasks
    )

    if tracks is None:
        raise HTTPException(status_code=404, detail="Tracks not found for this release group")
    
    return {"tracks": tracks}
