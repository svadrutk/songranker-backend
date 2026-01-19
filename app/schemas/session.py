from pydantic import BaseModel, UUID4
from typing import List, Optional
from datetime import datetime

class SongInput(BaseModel):
    name: str
    artist: str
    album: Optional[str] = None
    spotify_id: Optional[str] = None
    cover_url: Optional[str] = None

class SessionCreate(BaseModel):
    user_id: Optional[UUID4] = None
    songs: List[SongInput]

class SessionResponse(BaseModel):
    session_id: UUID4
    count: int

class SessionSummary(BaseModel):
    session_id: UUID4
    created_at: datetime
    primary_artist: str
    song_count: int
    comparison_count: int

class SessionSong(BaseModel):
    song_id: UUID4
    name: Optional[str] = "Unknown Track"
    artist: Optional[str] = "Unknown Artist"
    album: Optional[str] = None
    spotify_id: Optional[str] = None
    cover_url: Optional[str] = None
    local_elo: float
    bt_strength: Optional[float] = None

class SessionDetail(BaseModel):
    session_id: UUID4
    songs: List[SessionSong]
    comparison_count: int
    convergence_score: Optional[int] = None

class ComparisonCreate(BaseModel):
    song_a_id: UUID4
    song_b_id: UUID4
    winner_id: Optional[UUID4] = None
    is_tie: bool = False

class ComparisonResponse(BaseModel):
    success: bool
    new_elo_a: float
    new_elo_b: float
    sync_queued: bool = False
    convergence_score: Optional[int] = None
