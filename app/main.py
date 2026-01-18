import asyncio
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.api.v1 import search
from app.core.config import settings
from app.clients.supabase_db import supabase_client

async def cleanup_task():
    """Periodic background task to clean up expired cache from Supabase."""
    while True:
        try:
            await supabase_client.delete_expired_cache()
        except Exception:
            pass
        # Run every 6 hours
        await asyncio.sleep(6 * 3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: Initialize shared httpx client
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
        headers={"User-Agent": settings.MUSICBRAINZ_USER_AGENT}
    )
    
    # Start background cleanup
    app.state.cleanup_job = asyncio.create_task(cleanup_task())
    
    yield
    
    # Teardown
    app.state.cleanup_job.cancel()
    await app.state.http_client.aclose()

app = FastAPI(title="SongRanker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(search.router, tags=["search"])

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
