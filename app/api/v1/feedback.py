import logging
from fastapi import APIRouter, HTTPException, Request
from app.schemas.feedback import FeedbackCreate, FeedbackResponse
from app.clients.supabase_db import supabase_client
from app.core.limiter import limiter
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/feedback", response_model=FeedbackResponse)
@limiter.limit("5/minute")
async def create_feedback(request: Request, feedback: FeedbackCreate):
    """
    Submit user feedback, bug reports, or feature requests.
    """
    try:
        result = await supabase_client.create_feedback(
            message=feedback.message,
            user_id=str(feedback.user_id) if feedback.user_id else None,
            user_agent=feedback.user_agent,
            url=feedback.url
        )
        
        return FeedbackResponse(
            id=UUID(result["id"]),
            message=result["message"],
            created_at=result["created_at"]
        )
    except Exception as e:
        logger.error(f"Failed to create feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))
