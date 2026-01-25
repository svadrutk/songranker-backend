from pydantic import BaseModel, UUID4
from typing import Optional
from datetime import datetime

class FeedbackCreate(BaseModel):
    message: str
    user_id: Optional[UUID4] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None

class FeedbackResponse(BaseModel):
    id: UUID4
    message: str
    created_at: datetime
