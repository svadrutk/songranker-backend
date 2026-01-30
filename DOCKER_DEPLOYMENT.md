# Docker Deployment Guide

## Quick Start

### Single Container (Production - Railway/Render)

The default `Dockerfile` runs everything in one container:

```bash
# Build the image
docker build -t songranker-backend .

# Run with environment variables
docker run -p 8000:8000 \
  -e REDIS_URL=redis://your-redis-host:6379/0 \
  -e SPOTIFY_CLIENT_ID=your_id \
  -e SPOTIFY_CLIENT_SECRET=your_secret \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_SERVICE_ROLE_KEY=your_key \
  songranker-backend
```

This automatically starts:
- **Gunicorn** (4 workers) on port 8000
- **Default Worker** (1 instance) - handles ranking/deduplication
- **Spotify Worker** (1 instance) - handles Spotify API calls with rate limiting
- **Leaderboard Worker** (1 instance) - handles heavy global ranking calculations

### Docker Compose (Development)

For local development with proper service isolation:

```bash
# Start all services
docker-compose up

# Start in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose up --build
```

## Service Architecture (Docker Compose)

```yaml
services:
  redis:        # Redis server (required for workers)
  web:          # FastAPI application (4 Gunicorn workers)
  worker_default:   # Ranking/deduplication worker (can scale)
  worker_spotify:   # Spotify API worker (MUST be 1 replica)
  worker_leaderboard: # Heavy global ranking worker (can scale)
```

## Verifying Workers are Running

### Check Container Processes

```bash
# List all running containers
docker-compose ps

# Should show:
# - redis (healthy)
# - web (running)
# - worker_default (running)
# - worker_spotify (running)
# - worker_leaderboard (running)

# View logs for a specific worker
docker-compose logs -f worker_spotify

# You should see:
# "Starting RQ worker listening on queues: ['spotify']"
# "*** Listening on spotify..."
```

### Check Redis Queue Status

```bash
# Connect to Redis container
docker-compose exec redis redis-cli

# Check queue lengths
LLEN rq:queue:default
LLEN rq:queue:spotify
LLEN rq:queue:leaderboard

# List all keys (for debugging)
KEYS rq:*
```

## Scaling Workers

### Safe Scaling

```bash
# Scale default worker (safe - can be multiple)
docker-compose up --scale worker_default=3

# The web and spotify worker remain at 1 replica
```

### ⚠️ CRITICAL: Never Scale Spotify Worker

```bash
# ❌ DON'T DO THIS - breaks rate limiting!
docker-compose up --scale worker_spotify=2

# ✅ Always keep at 1 replica
docker-compose up --scale worker_spotify=1
```

## Environment Variables

Create a `.env` file in the project root:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# Spotify
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret

# Last.fm
LASTFM_API_KEY=your-api-key
LASTFM_SHARED_SECRET=your-shared-secret

# Redis (automatically set in docker-compose)
REDIS_URL=redis://redis:6379/0
```

## Production Deployment

### Railway

Railway will use the `Dockerfile`:

1. Connect your GitHub repo
2. Add environment variables in the Railway dashboard
3. Deploy - Railway automatically runs the `CMD` which starts all processes

**Important:** The single container approach is fine for Railway because:
- All processes (web + workers) run in the same container
- Only 1 Spotify worker will ever exist
- Railway scales by creating **new containers**, not new workers within a container

### Render

Similar to Railway:

1. Create a new "Web Service"
2. Use the `Dockerfile`
3. Set environment variables
4. Deploy

### Heroku (Multi-Dyno)

For Heroku, use the `Procfile` instead:

```bash
# Deploy
git push heroku main

# Scale dynos
heroku ps:scale web=1 worker_default=1 worker_spotify=1 worker_leaderboard=1

# Check status
heroku ps
```

## Troubleshooting

### Workers Not Starting

**Check Logs:**
```bash
docker-compose logs worker_spotify
docker-compose logs worker_default
```

**Common Issues:**
- Missing environment variables (especially `REDIS_URL`)
- Redis not running or unhealthy
- Port conflicts

**Solution:**
```bash
# Restart everything
docker-compose down
docker-compose up --build
```

### Redis Connection Issues

**Check Redis Health:**
```bash
docker-compose exec redis redis-cli ping
# Should return: PONG
```

**Check Redis URL:**
```bash
docker-compose exec web env | grep REDIS_URL
# Should be: redis://redis:6379/0
```

### Spotify Worker Not Processing Jobs

**Check Worker Status:**
```bash
# See if worker is idle or processing
docker-compose logs -f worker_spotify

# Check queue length
docker-compose exec redis redis-cli LLEN rq:queue:spotify
```

**If queue is backing up:**
- Worker might be stuck on a slow request
- Check for timeout errors in logs
- Restart the worker: `docker-compose restart worker_spotify`

### Building Takes Too Long

The Playwright installation can take 1-2 minutes. This is normal.

**Speed up rebuilds:**
```bash
# Use Docker layer caching
docker-compose build --parallel

# Only rebuild specific service
docker-compose build web
```

## Performance Tuning

### Gunicorn Workers

Adjust in `Dockerfile` or `docker-compose.yml`:

```yaml
# For 2 CPU cores
command: gunicorn app.main:app --workers 2 ...

# For 8 CPU cores
command: gunicorn app.main:app --workers 8 ...
```

Rule of thumb: `workers = (2 × CPU cores) + 1`

### Default Worker Replicas

```bash
# High ranking load
docker-compose up --scale worker_default=3

# Low load
docker-compose up --scale worker_default=1
```

### Redis Memory

For production, consider adding to `docker-compose.yml`:

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
```

## Monitoring

### Health Checks

All services have health checks defined. Check status:

```bash
docker-compose ps

# Healthy services show: "Up (healthy)"
# Unhealthy services show: "Up (unhealthy)"
```

### Resource Usage

```bash
# See CPU and memory usage
docker stats

# For specific container
docker stats songranker-backend-worker_spotify-1
```

## Clean Up

```bash
# Stop and remove containers
docker-compose down

# Also remove volumes (Redis data)
docker-compose down -v

# Remove images
docker-compose down --rmi all

# Nuclear option - remove everything
docker system prune -a --volumes
```
