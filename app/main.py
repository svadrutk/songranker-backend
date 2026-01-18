from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.api.v1 import search
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: Initialize shared httpx client
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
        headers={"User-Agent": settings.MUSICBRAINZ_USER_AGENT}
    )
    yield
    # Teardown: Close the client
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
