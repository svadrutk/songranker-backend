# SongRanker Backend

FastAPI backend for the SongRanker application.

## Features

- **Session-based Ranking**: Personal song rankings using Bradley-Terry model
- **Global Leaderboard**: Platform-wide rankings aggregated across all users
- **Smart Deduplication**: Automated fuzzy matching to eliminate duplicate songs
- **Background Workers**: Async ranking calculations via Redis/RQ
- **Caching**: Redis-based caching for fast API responses

## API Endpoints

### Search & Sessions
- `GET /search` - Search for artists and albums
- `GET /tracks/{release_group_id}` - Get track list for an album
- `POST /sessions` - Create new ranking session
- `GET /sessions/{session_id}` - Get session details
- `POST /sessions/{session_id}/comparisons` - Record a song comparison

### Global Leaderboard (New)
- `GET /leaderboard/{artist}` - Get top songs for an artist (global rankings)
- `GET /leaderboard/{artist}/stats` - Get artist statistics

### Image Generation
- `POST /generate-receipt` - Generate shareable receipt image

## API Specification Sync

To keep the frontend API client up to date, we maintain an `openapi.json` file in the `songranker-frontend` directory.

### Automation
Whenever the API structure changes, run:

```bash
python scripts/export_openapi.py
```

This script:
1. Extracts the OpenAPI schema from the FastAPI app
2. Saves it to `../songranker-frontend/openapi.json`
3. Updates TypeScript types for the frontend

## Recent Updates

### 2026-01-24 - Global Leaderboard
- **Added**: Global leaderboard endpoints for cross-session rankings
- **Performance**: Batch + interval update strategy (10-min intervals per artist)
- **Caching**: Redis caching with 2-minute TTL for leaderboard queries
- **Database**: New `artist_stats` table and global ranking columns in `songs` table
- **Migration**: Run `supabase_global_leaderboard.sql` to update schema
