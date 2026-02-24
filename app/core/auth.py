import jwt
import logging
from typing import Optional
from fastapi import Request
from app.core.config import settings

logger = logging.getLogger(__name__)

def get_user_id_from_request(request: Request) -> Optional[str]:
    """
    Extract the Supabase user ID from the Authorization header.
    Does NOT verify the signature, just decodes the payload.
    This is used for UI hints like 'is_owner'.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    try:
        # Decode without verification to get the 'sub' field
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload.get("sub")
    except Exception as e:
        logger.warning(f"Failed to decode JWT: {e}")
        return None
