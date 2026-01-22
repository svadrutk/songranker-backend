import asyncio
import logging
from app.clients.supabase_db import supabase_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_rpc_summaries():
    user_id = "5a9e0b21-3caf-4936-b33c-af60bed6d23e"
    
    try:
        client = await supabase_client.get_client()
        
        logger.info(f"Testing RPC get_user_session_summaries for user: {user_id}")
        res = await client.rpc("get_user_session_summaries", {"p_user_id": user_id}).execute()
        
        data = res.data
        if isinstance(data, list) and len(data) > 0:
            first_row = data[0]
            logger.info(f"Successfully retrieved {len(data)} sessions")
            if isinstance(first_row, dict):
                logger.info(f"Available keys: {list(first_row.keys())}")
                logger.info(f"First session sample: {first_row}")
        else:
            logger.warning("No session data returned from RPC")

            
    except Exception as e:
        logger.error(f"RPC test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_rpc_summaries())

