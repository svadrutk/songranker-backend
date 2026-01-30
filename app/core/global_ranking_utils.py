"""Utility functions for global ranking system."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from app.core.global_ranking_config import GLOBAL_UPDATE_INTERVAL_MINUTES

logger = logging.getLogger(__name__)


def calculate_pending_comparisons(
    total_comparisons: int, 
    stats: Optional[Dict[str, Any]]
) -> tuple[int, int]:
    """
    Calculate processed and pending comparisons.
    
    Args:
        total_comparisons: Total number of comparisons made
        stats: Artist stats dictionary from database
    
    Returns:
        Tuple of (processed_comparisons, pending_comparisons)
    """
    processed = stats.get("total_comparisons_count", 0) if stats else 0
    pending = max(0, total_comparisons - processed)
    return processed, pending


def parse_timestamp(timestamp: str | datetime) -> datetime:
    """
    Parse a timestamp string or datetime into a UTC datetime object.
    
    Args:
        timestamp: ISO format string or datetime object
    
    Returns:
        datetime object in UTC timezone
    """
    if isinstance(timestamp, str):
        return datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return timestamp


def get_seconds_since_update(last_updated: str | datetime) -> float:
    """
    Get seconds elapsed since the last update.
    
    Args:
        last_updated: ISO format string or datetime object
    
    Returns:
        Seconds elapsed since last update
    """
    last_update_dt = parse_timestamp(last_updated)
    return (datetime.now(timezone.utc) - last_update_dt).total_seconds()


def is_update_stale(last_updated: str | datetime) -> bool:
    """
    Check if the last update is older than the threshold.
    
    Args:
        last_updated: ISO format string or datetime object
    
    Returns:
        True if update is stale (older than threshold), False otherwise
    """
    seconds_since = get_seconds_since_update(last_updated)
    threshold_seconds = GLOBAL_UPDATE_INTERVAL_MINUTES * 60
    return seconds_since >= threshold_seconds


async def should_trigger_global_update(
    artist: str,
    last_updated: Optional[str | datetime],
    pending_comparisons: int = 0
) -> bool:
    """
    Check if a global ranking update should be triggered.
    
    Args:
        artist: The artist name
        last_updated: Timestamp of last update (ISO string or datetime)
        pending_comparisons: Number of pending comparisons (for logging)
    
    Returns:
        True if update should be triggered, False otherwise
    """
    if pending_comparisons == 0:
        logger.debug(f"[GLOBAL] No pending comparisons for artist='{artist}' - skipping")
        return False
    
    if not last_updated:
        logger.info(f"[GLOBAL] No previous update for artist='{artist}' - triggering first update")
        return True
    
    seconds_since = get_seconds_since_update(last_updated)
    threshold_seconds = GLOBAL_UPDATE_INTERVAL_MINUTES * 60
    
    if seconds_since < threshold_seconds:
        logger.info(
            f"[GLOBAL] Skipping update for artist='{artist}' - "
            f"only {seconds_since/60:.1f}m since last update (Threshold: {GLOBAL_UPDATE_INTERVAL_MINUTES}m)"
        )
        return False
    
    logger.info(
        f"[GLOBAL] Triggering update for artist='{artist}' - "
        f"{pending_comparisons} pending, {seconds_since/60:.1f}m since last update"
    )
    return True
