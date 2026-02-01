from pydantic import BaseModel, Field, UUID4
from typing import Optional
from datetime import datetime

class FeedbackCreate(BaseModel):
    message: str
    user_id: Optional[UUID4] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None
    session_id: Optional[UUID4] = None
    star_rating: Optional[int] = Field(None, ge=1, le=5, description="Star rating from 1 to 5")

class FeedbackResponse(BaseModel):
    id: UUID4
    message: str
    created_at: datetime
