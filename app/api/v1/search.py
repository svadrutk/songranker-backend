import logging
from typing import List, Optional, Dict, Any, cast
import httpx
from fastapi import APIRouter, HTTPException, Query, Request, BackgroundTasks
from pydantic import BaseModel
import asyncio
import re

from app.clients.musicbrainz import musicbrainz_client
from app.clients.lastfm import lastfm_client
from app.clients.spotify import spotify_client
from app.core.utils import normalize_title, is_spotify_id, DELUXE_KEYWORDS, SKIP_KEYWORDS
from app.core.cache import cache
from app.core.limiter import limiter
from app.core.config import settings

logger = logging.getLogger(__name__)

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

async def _resolve_mbid_background(artist: str, title: str, spotify_id: str, client: httpx.AsyncClient):
    """
    Background task to find the MusicBrainz ID for a Spotify album.
    Stores the link in the cache for future consistency.
    """
    try:
        # Search for the specific release group
        mbid = await musicbrainz_client.search_release_group(artist, title, client=client)
        if mbid:
            # Store the mapping so we know this Spotify ID maps to this MBID
            # TODO: Add reader for this cache to bridge Spotify IDs to MBIDs in other endpoints
            await cache.get_or_fetch(
                f"spotify_map:{spotify_id}",
                lambda: mbid,
                ttl_seconds=86400 * 30 # 30 days
            )
    except Exception as e:
        logger.error(f"Error resolving MBID for Spotify ID {spotify_id}: {e}")

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

def _should_skip_title(title: str) -> bool:
    """Check if title contains keywords that should be excluded."""
    return any(kw in title.lower() for kw in SKIP_KEYWORDS)

def _is_deluxe_title(title: str) -> bool:
    """Check if title indicates a Deluxe edition."""
    return any(kw in title.lower() for kw in DELUXE_KEYWORDS)

def _create_album_entry(album: Dict, mb_entry: Optional[Dict], mbid: str, default_artist: str) -> Dict:
    """Create a standardized album entry object."""
    return {
        "id": mbid,
        "title": album["title"],
        "artist": album.get("artist") or default_artist,
        "type": mb_entry["type"] if mb_entry else "Album",
        "cover_art": {
            "front": bool(album["image_url"]),
            "url": album["image_url"]
        }
    }

def _merge_results(lastfm_albums: List[Dict], mb_release_groups: List[Dict], default_artist: str) -> List[Dict]:
    """
    Merge and deduplicate results from both sources with specific preference rules:
    1. Filter out skipped keywords
    2. Match Last.fm albums to MusicBrainz entries by normalized title
    3. Deduplicate by MBID (keeping the first one seen)
    4. Handle title collisions: Prefer Deluxe editions if available
    """
    # Index MusicBrainz results for O(1) lookup
    mb_lookup = {
        normalize_title(rg["title"]): rg 
        for rg in mb_release_groups 
        if normalize_title(rg["title"])
    }
    
    results_by_title: Dict[str, Dict] = {}
    seen_mbids: set[str] = set()

    for album in lastfm_albums:
        title = album["title"]
        if _should_skip_title(title):
            continue

        norm_title = normalize_title(title)
        mb_entry = mb_lookup.get(norm_title)
        
        # Determine MBID: prioritize explicit Last.fm MBID, fallback to MB lookup
        mbid = album.get("mbid") or (mb_entry["id"] if mb_entry else None)
        
        # Skip if no ID or if ID already processed (duplicates)
        if not mbid or mbid in seen_mbids:
            continue
            
        new_entry = _create_album_entry(album, mb_entry, mbid, default_artist)
        
        # Case 1: New title - add it
        if norm_title not in results_by_title:
            results_by_title[norm_title] = new_entry
            seen_mbids.add(mbid)
            continue
            
        # Case 2: Existing title - check if we should upgrade to Deluxe
        existing_entry = results_by_title[norm_title]
        if _is_deluxe_title(title) and not _is_deluxe_title(existing_entry["title"]):
            seen_mbids.remove(existing_entry["id"])
            results_by_title[norm_title] = new_entry
            seen_mbids.add(mbid)
    
    return list(results_by_title.values())

@router.get("/search", response_model=List[ReleaseGroupResponse])
@limiter.limit("30/minute")
async def search(request: Request, background_tasks: BackgroundTasks, query: str = Query(..., min_length=1)):
    client = request.app.state.http_client
    
    # 1. Normalize query for typo/alias cache
    norm_query = re.sub(r'[^a-z0-9]', '', query.lower()).strip()
    if not norm_query:
        return []

    # 2. FAST PATH: Spotify
    # If credentials are present, use Spotify as the primary search engine.
    # It is faster (200ms vs 1s+) and handles typos natively.
    # Route through dedicated worker for rate limiting.
    if settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET:
        cache_key = f"spotify_search:{norm_query}"
        results = await cache.get_or_fetch(
            cache_key,
            lambda: spotify_client.call_via_worker("search_artist_albums", artist_name=query),
            ttl_seconds=3600,
            background_tasks=background_tasks
        )
        if results:
            return results

    # 3. Get Artist Context (Alias Cache)
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

    # 4. Get Artist Albums (Canonical Cache)
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

async def _fetch_tracks_parallel(
    release_group_id: str, 
    artist: Optional[str], 
    title: Optional[str], 
    client: httpx.AsyncClient
) -> List[List[str]]:
    """Fetch tracks from multiple sources in parallel."""
    tasks = [
        lastfm_client.get_album_tracks(release_group_id, client=client),
        musicbrainz_client.get_release_group_tracks(release_group_id, client=client)
    ]
    
    if artist and title:
        custom_id = f"{artist}:{title}"
        tasks.append(lastfm_client.get_album_tracks(custom_id, client=client))
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, list) and len(r) > 0]


async def _fetch_tracks_fallback(release_group_id: str, client: httpx.AsyncClient) -> Optional[List[str]]:
    """Try to resolve release group info and search Last.fm by name as a last resort."""
    try:
        info = await musicbrainz_client.get_release_group_info(release_group_id, client=client)
        if info.get("artist") and info.get("title"):
             return await lastfm_client.get_album_tracks(f"{info['artist']}:{info['title']}", client=client)
    except Exception as e:
        logger.debug(f"Fallback search failed for {release_group_id}: {e}")
    return None


@router.get("/tracks/{release_group_id}", response_model=TrackResponse)
async def get_tracks(
    request: Request, 
    background_tasks: BackgroundTasks, 
    release_group_id: str,
    artist: Optional[str] = Query(None),
    title: Optional[str] = Query(None)
):
    """Fetch track titles with a parallelized race strategy and intelligent merging."""
    logger.info(f"GET /tracks/{release_group_id} (artist={artist}, title={title})")
    client = request.app.state.http_client
    
    async def fetch_tracks() -> Optional[List[str]]:
        logger.info(f"Starting fetch_tracks for {release_group_id}")
        
        # 1. Fast Path: Spotify ID Detection
        if is_spotify_id(release_group_id):
             logger.info(f"Spotify ID detected: {release_group_id}")
             if artist and title:
                 background_tasks.add_task(_resolve_mbid_background, artist, title, release_group_id, client)
             return await spotify_client.call_via_worker("get_album_tracks", spotify_id=release_group_id)

        # 2. Parallel Strategy
        valid_results = await _fetch_tracks_parallel(release_group_id, artist, title, client)
        
        # 3. Fallback Strategy
        if not valid_results and not (artist and title):
            fallback_res = await _fetch_tracks_fallback(release_group_id, client)
            if fallback_res:
                valid_results.append(fallback_res)

        if not valid_results:
            return None

        # 4. Intelligent Merging: Pick the "best" result (most tracks)
        return max(valid_results, key=len)

    tracks = await cache.get_or_fetch(
        f"tracks:{release_group_id}",
        fetch_tracks,
        ttl_seconds=86400, # 24 hours
        background_tasks=background_tasks
    )

    if tracks is None:
        raise HTTPException(status_code=404, detail="Tracks not found for this release group")
    
    return {"tracks": tracks}

@router.get("/debug/flush")
async def flush_cache():
    """Wipe the in-memory cache for testing."""
    from collections import OrderedDict
    cache._memory_cache = OrderedDict()
    return {"message": "Memory cache flushed successfully"}

