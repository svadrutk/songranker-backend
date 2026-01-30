"""Configuration constants for global ranking system."""

# How often global rankings update (minutes)
GLOBAL_UPDATE_INTERVAL_MINUTES = 2

# Redis lock expiry time (seconds)
# Should be longer than max expected update duration
REDIS_LOCK_EXPIRY_SECONDS = 120  # 2 minutes (cooldown)

# Lock key format
GLOBAL_UPDATE_LOCK_KEY_FORMAT = "global_update_lock:{artist}"


def get_global_update_lock_key(artist: str) -> str:
    """Get Redis lock key for a specific artist's global update."""
    # Normalize artist name for the lock key to prevent duplicate updates 
    # for variations like "Demi Lovato" and "demi lovato"
    return GLOBAL_UPDATE_LOCK_KEY_FORMAT.format(artist=artist.lower())
