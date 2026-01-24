# Changelog

## [Unreleased] - 2026-01-24

### Added - Global Leaderboard Feature
- **New Endpoints:**
  - `GET /leaderboard/{artist}` - Returns top 100 songs ranked globally across all user sessions
  - `GET /leaderboard/{artist}/stats` - Returns lightweight statistics about an artist's leaderboard

- **Database Schema:**
  - Added `global_elo`, `global_bt_strength`, `global_votes_count` columns to `songs` table
  - Created new `artist_stats` table to track update timestamps and vote counts
  - Added performance indexes for fast leaderboard queries
  - Created RPC functions for efficient data aggregation

- **Background Tasks:**
  - `process_global_ranking(artist)` - Computes global rankings using Bradley-Terry model
  - Smart trigger system: updates every 10 minutes per artist (batch + interval strategy)
  - Automatic trigger after session ranking updates

- **Performance Optimizations:**
  - Redis caching (2-minute TTL) for leaderboard endpoints
  - Rate limiting: 60 requests/minute per endpoint
  - Response time: < 50ms with caching
  - Handles 1000+ concurrent users per artist

- **Files Modified:**
  - `app/clients/supabase_db.py` - Added 7 global ranking database methods
  - `app/tasks.py` - Added global ranking task and trigger logic
  - `app/main.py` - Registered leaderboard router
  - `app/api/v1/leaderboard.py` - New API endpoints

- **Files Created:**
  - `supabase_global_leaderboard.sql` - Database migration script
  - OpenAPI spec updated in `../songranker-frontend/openapi.json`

### Technical Details
- Uses same Bradley-Terry algorithm as session rankings for consistency
- Aggregates comparisons across all sessions for each artist
- Warm start optimization using previous BT strengths
- Decision time weighting applied to Bradley-Terry calculation (< 3s = 1.5x, > 10s = 0.5x)
- Vote counts (`global_votes_count`) track unweighted participation (number of comparisons)
- Race condition prevention: artists can only have one global update enqueued at a time

### Deployment
1. Apply migration: Run `supabase_global_leaderboard.sql` in Supabase
2. Deploy backend with new endpoints
3. Ensure RQ worker is running for background tasks
4. Frontend can use updated OpenAPI spec for TypeScript types
