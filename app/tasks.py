import asyncio
import logging
from app.core.deduplication import deep_deduplicate_session

logger = logging.getLogger(__name__)

def run_deep_deduplication(session_id: str):
    """
    Synchronous wrapper for the async deduplication task.
    This is what the RQ worker calls.
    """
    logger.info(f"Worker processing deduplication for session {session_id}")
    try:
        asyncio.run(deep_deduplicate_session(session_id))
    except Exception as e:
        logger.error(f"Worker failed deduplication for {session_id}: {e}")
        raise
