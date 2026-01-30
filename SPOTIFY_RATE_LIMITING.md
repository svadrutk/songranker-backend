# Spotify Rate Limiting Architecture

## Overview

This backend implements a **dedicated worker queue** for all Spotify API calls to prevent rate limiting across multiple Gunicorn instances. By serializing all Spotify traffic through a single worker, we ensure that the app never exceeds Spotify's rate limits, even under heavy load.

## Architecture

### Three-Queue System

1. **`default` Queue (Ranking & Math)**
   - Handles session Bradley-Terry ranking computations
   - Processes session deduplication
   - Fast, CPU-bound tasks
   - Can scale to multiple workers if needed

2. **`spotify` Queue (API Rate Limiting)**
   - Handles all Spotify API calls
   - **MUST run with exactly 1 worker** (critical for rate limiting)
   - Network-bound tasks
   - Serializes traffic to prevent 429 errors

3. **`leaderboard` Queue (Global Math)**
   - Handles heavy global ranking calculations
   - Periodic, expensive tasks
   - Isolated to prevent blocking user-facing tasks
   - Can scale as needed

### How It Works

```
┌─────────────────┐
│  Gunicorn Web   │  (4 workers)
│   Instance 1    │
└────────┬────────┘
         │
         │  All Spotify calls
         │  enqueued to Redis
         ▼
┌─────────────────────────────────┐
│         Redis Queue             │
│      (spotify queue)            │
└────────┬────────────────────────┘
         │
         │  Processed one-at-a-time
         ▼
┌─────────────────┐
│ Spotify Worker  │  (1 worker only!)
│   (Serialized)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Spotify API    │
└─────────────────┘
```

### Rate Limiting Features

1. **Serialization**: Only 1 worker = Only 1 request at a time
2. **Retry Logic**: Uses `tenacity` to automatically retry on:
   - `429 Too Many Requests`
   - `5xx` server errors
   - Connection timeouts
3. **Exponential Backoff**: Waits 2s, 4s, up to 30s between retries

## Deployment

### Local Development

```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start Default Worker (ranking/math)
uv run python worker.py --queues default

# Terminal 3: Start Spotify Worker (IMPORTANT: only 1 instance!)
uv run python worker.py --queues spotify

# Terminal 4: Start API
uv run uvicorn app.main:app --reload
```

### Production (Heroku/Render)

The `Procfile` defines the process types:

```
web: gunicorn app.main:app --workers 4 ...
worker_default: python worker.py --queues default
worker_spotify: python worker.py --queues spotify
```

**Critical:** Ensure that `worker_spotify` is scaled to **exactly 1 dyno/instance**. Scaling to 2+ will break rate limiting.

### Heroku Scaling

```bash
# Scale the web layer (API)
heroku ps:scale web=2

# Scale the default worker (can be multiple)
heroku ps:scale worker_default=2

# Scale the Spotify worker (MUST be 1)
heroku ps:scale worker_spotify=1
```

### Docker

#### Single Container (Railway/Render)

The `Dockerfile` runs all processes in one container:

```bash
docker build -t songranker-backend .
docker run -p 8000:8000 --env-file .env songranker-backend
```

This starts:
- 1 web server (Gunicorn with 4 workers)
- 1 default worker (ranking/math)
- 1 Spotify worker (rate limiting)

#### Docker Compose (Local Development)

For proper service separation:

```bash
# Start all services (web + redis + both workers)
docker-compose up

# Scale the default worker (optional)
docker-compose up --scale worker_default=2

# IMPORTANT: Never scale worker_spotify beyond 1!
```

Services:
- `redis`: Redis server on port 6379
- `web`: API server on port 8000
- `worker_default`: Ranking/deduplication worker (can scale)
- `worker_spotify`: Spotify API worker (MUST be 1 replica)

## Configuration

### Environment Variables

```bash
# Required for Spotify integration
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret

# Redis connection
REDIS_URL=redis://localhost:6379/0
```

### Settings (`app/core/config.py`)

- `SPOTIFY_PAUSE_KEY`: Redis key for global pause (currently unused, reserved for future enhancements)

## Usage in Code

### API Layer (`app/api/v1/search.py`)

**Before (Direct Call - Rate Limit Risk):**
```python
albums = await spotify_client.search_artist_albums(query, client)
```

**After (Worker Proxy - Rate Limited):**
```python
albums = await spotify_client.call_via_worker(
    "search_artist_albums",
    artist_name=query
)
```

### How the Proxy Works

1. API receives a search request
2. `call_via_worker()` enqueues task to Redis (`spotify` queue)
3. API polls the job status every 100ms
4. Spotify worker picks up the task (serialized)
5. Worker executes the Spotify API call
6. Worker stores result in Redis
7. API retrieves result and returns to user

**Latency Impact:** +50-150ms overhead due to Redis roundtrip, but this is acceptable for the stability gained.

## Testing

### Quick Test

```bash
# Make sure Redis and Spotify worker are running
uv run python test_spotify_worker.py
```

This will:
1. Search for "Taylor Swift"
2. Fetch tracks from the first album
3. Verify the worker proxy is functioning

### Manual Testing

```bash
# Check queue status
redis-cli
> LLEN rq:queue:spotify
> LRANGE rq:queue:spotify 0 -1
```

## Troubleshooting

### "TimeoutError: Spotify worker timed out"

**Cause:** Worker is not running or is overloaded.

**Solution:**
```bash
# Check if worker is running
ps aux | grep "worker.py --queues spotify"

# Check Redis queue length
redis-cli LLEN rq:queue:spotify

# Restart worker
python worker.py --queues spotify
```

### "Still getting 429 errors"

**Cause:** Multiple Spotify workers are running.

**Solution:**
```bash
# Kill all Spotify workers
pkill -f "worker.py --queues spotify"

# Start only 1 worker
python worker.py --queues spotify
```

### "Searches are slow"

**Expected:** The worker proxy adds 50-150ms latency. This is the trade-off for rate limiting.

**If > 500ms:**
- Check Redis latency: `redis-cli --latency`
- Check worker queue backlog: `redis-cli LLEN rq:queue:spotify`
- Consider increasing worker timeout if network is slow

## Future Enhancements

1. **Global Pause Mechanism**
   - When any worker gets a `429`, set a Redis key with TTL = `Retry-After`
   - All workers check this key before making requests
   - This would allow scaling to 2-3 Spotify workers safely

2. **Bulk Ingestion ("Rank All")**
   - Add `import_spotify_artist` task
   - Incrementally fetch albums/tracks
   - Commit to DB after each album for "streaming" UX

3. **Metrics & Monitoring**
   - Track Spotify API call rate
   - Alert if queue length > 100
   - Dashboard for worker health

## References

- **RQ (Redis Queue)**: https://python-rq.org/
- **Tenacity (Retry Library)**: https://tenacity.readthedocs.io/
- **Spotify API Rate Limits**: https://developer.spotify.com/documentation/web-api/concepts/rate-limits
