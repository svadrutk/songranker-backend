from pydantic import BaseModel, UUID4
from typing import List, Optional

class SongInput(BaseModel):
    name: str
    artist: str
    album: Optional[str] = None
    spotify_id: Optional[str] = None

class SessionCreate(BaseModel):
    user_id: Optional[UUID4] = None
    songs: List[SongInput]

class SessionResponse(BaseModel):
    session_id: UUID4
    count: int
