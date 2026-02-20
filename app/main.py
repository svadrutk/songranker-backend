from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter
from app.api.v1 import search, sessions, image_generation, leaderboard, feedback, imports
from app.core.config import settings

import logging
import sys

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: Initialize shared httpx client with higher limits for concurrency
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=200)
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=True,
        headers={"User-Agent": settings.MUSICBRAINZ_USER_AGENT},
        limits=limits
    )
    
    yield
    
    # Teardown
    await app.state.http_client.aclose()

app = FastAPI(title="SongRanker API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(search.router, tags=["search"])
app.include_router(sessions.router, tags=["sessions"])
app.include_router(imports.router, tags=["imports"])
app.include_router(image_generation.router, tags=["image-generation"])
app.include_router(leaderboard.router, tags=["leaderboard"])
app.include_router(feedback.router, tags=["feedback"])

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/health/redis")
async def redis_health_check():
    """Check Redis connection for worker queue."""
    try:
        from app.core.queue import sync_redis_conn
        # Test Redis connection
        sync_redis_conn.ping()
        return {
            "status": "healthy",
            "redis_url": settings.REDIS_URL,
            "message": "Redis connection successful"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "redis_url": settings.REDIS_URL,
            "error": str(e),
            "message": "Redis connection failed"
        }

@app.get("/health/worker")
async def worker_health_check():
    """Check worker status and queue."""
    try:
        from app.core.queue import task_queue, sync_redis_conn
        from rq import Worker
        
        # Get worker info
        workers = Worker.all(connection=sync_redis_conn)
        worker_info = []
        for worker in workers:
            worker_info.append({
                "name": worker.name,
                "state": worker.state,
                "queues": [q.name for q in worker.queues]
            })
        
        # Get queue info
        queue_length = len(task_queue)
        
        return {
            "status": "healthy",
            "workers": worker_info,
            "queue_length": queue_length,
            "redis_url": settings.REDIS_URL
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "redis_url": settings.REDIS_URL
        }
