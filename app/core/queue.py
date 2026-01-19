import redis.asyncio as redis
from rq import Queue
from app.core.config import settings

# Create sync Redis connection for RQ
import redis as redis_sync
sync_redis_conn = redis_sync.from_url(settings.REDIS_URL)

# Create async Redis connection for the API cache
redis_conn = redis.from_url(settings.REDIS_URL)

# Initialize the queue
# 'default' is the name of the queue
task_queue = Queue("default", connection=sync_redis_conn)
