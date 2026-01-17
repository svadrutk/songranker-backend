from typing import List, Optional, Dict, Any, cast
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
import asyncio

from app.clients.musicbrainz import musicbrainz_client
from app.clients.lastfm import lastfm_client
from app.core.utils import normalize_title, DELUXE_KEYWORDS, SKIP_KEYWORDS

router = APIRouter()

def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client

class CoverArtArchive(BaseModel):
    artwork: Optional[bool] = None
    back: Optional[bool] = None
    count: Optional[int] = None
    darkened: Optional[bool] = None
    front: Optional[bool] = None
    url: Optional[str] = None # Added for Last.fm images

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
        return None, None
    return artists[0]["name"], artists[0].get("mbid")

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
    
    # Use return_exceptions=True to prevent one failure from killing both tasks
    results = await asyncio.gather(lastfm_task, mb_task, return_exceptions=True)
    
    lastfm_res = cast(List[Dict[str, Any]], results[0] if not isinstance(results[0], Exception) else [])
    mb_res = cast(List[Dict[str, Any]], results[1] if not isinstance(results[1], Exception) else [])
    
    return lastfm_res, mb_res

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
async def search(request: Request, query: str = Query(..., min_length=1)):
    client = request.app.state.http_client
    try:
        artist_name, artist_mbid = await _get_artist_context(query, client)
        if not artist_name:
            return []

        lastfm_albums, mb_release_groups = await _fetch_release_data(artist_name, artist_mbid, client)
        results = _merge_results(lastfm_albums, mb_release_groups, artist_name)

        if not results and mb_release_groups:
            return mb_release_groups[:30]
                
        return results
    except Exception as e:
        # Final fallback to pure MusicBrainz
        try:
            mb_artists = await musicbrainz_client.search_artist(query, client=client)
            if not mb_artists: 
                return []
            return await musicbrainz_client.get_artist_release_groups(mb_artists[0]["id"], client=client)
        except Exception:
            raise HTTPException(status_code=500, detail=str(e) or "Internal Server Error during search")

@router.get("/tracks/{release_group_id}", response_model=TrackResponse)
async def get_tracks(request: Request, release_group_id: str):
    """Fetch track titles with a prioritized strategy fallback."""
    client = request.app.state.http_client
    
    # Strategy 1: Attempt Last.fm fetch first (fastest)
    try:
        tracks = await lastfm_client.get_album_tracks(release_group_id, client=client)
        if tracks:
            return {"tracks": tracks}
    except Exception:
        pass

    # Strategy 2: Fallback to MusicBrainz
    try:
        tracks = await musicbrainz_client.get_release_group_tracks(release_group_id, client=client)
        if tracks:
            return {"tracks": tracks}
    except Exception:
        pass

    # Strategy 3: Resolve MBID to Name and try Last.fm by Title (for new albums)
    try:
        info = await musicbrainz_client.get_release_group_info(release_group_id, client=client)
        if info.get("artist") and info.get("title"):
            custom_id = f"{info['artist']}:{info['title']}"
            tracks = await lastfm_client.get_album_tracks(custom_id, client=client)
            if tracks:
                return {"tracks": tracks}
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Tracks not found for this release group")
