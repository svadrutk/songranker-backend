from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.clients.musicbrainz import musicbrainz_client

router = APIRouter()

class CoverArtArchive(BaseModel):
    artwork: Optional[bool] = None
    back: Optional[bool] = None
    count: Optional[int] = None
    darkened: Optional[bool] = None
    front: Optional[bool] = None

class ReleaseGroupResponse(BaseModel):
    id: str
    title: str
    type: Optional[str] = None
    cover_art: CoverArtArchive

class TrackResponse(BaseModel):
    tracks: List[str]

@router.get("/search", response_model=List[ReleaseGroupResponse])
async def search(query: str = Query(..., min_length=1)):
    try:
        artists = await musicbrainz_client.search_artist(query)
        if not artists:
            return []
        
        artist_id = artists[0]["id"]
        # Use the optimized release-group browse
        release_groups = await musicbrainz_client.get_artist_release_groups(artist_id)
        return release_groups
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e) or "Internal Server Error during search")

@router.get("/tracks/{release_group_id}", response_model=TrackResponse)
async def get_tracks(release_group_id: str):
    try:
        tracks = await musicbrainz_client.get_release_group_tracks(release_group_id)
        if not tracks:
            raise HTTPException(status_code=404, detail="Tracks not found for this release group")
        return {"tracks": tracks}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e) or "Internal Server Error during track fetch")
