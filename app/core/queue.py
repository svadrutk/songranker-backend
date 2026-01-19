import redis.asyncio as redis
from rq import Queue
from app.core.config import settings

# Create sync Redis connection for RQ
import redis as redis_sync
sync_redis_conn = redis_sync.from_url(settings.REDIS_URL)

# Create async Redis connection for the API cache with a connection pool
# Lazy initialization to avoid side effects at import time
redis_conn = None

def get_async_redis():
    global redis_conn
    if redis_conn is None:
        redis_conn = redis.from_url(
            settings.REDIS_URL,
            max_connections=50,
            retry_on_timeout=True,
            health_check_interval=30
        )
    return redis_conn

# Initialize the queue
# 'default' is the name of the queue
task_queue = Queue("default", connection=sync_redis_conn)
