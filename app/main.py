from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import search
from app.core.config import settings

app = FastAPI(title="SongRanker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router, tags=["search"])

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
