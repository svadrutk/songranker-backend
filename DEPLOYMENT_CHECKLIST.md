# Deployment Checklist - Spotify Rate Limiting

## ✅ Pre-Deployment Verification

### 1. Code Changes
- [x] `app/core/queue.py` - Added `spotify_queue` and `leaderboard_queue`
- [x] `app/tasks.py` - Added `run_spotify_method()` worker task
- [x] `app/clients/spotify.py` - Added `call_via_worker()` proxy method
- [x] `app/api/v1/search.py` - Updated to use worker proxy
- [x] `worker.py` - Added `--queues` argument support
- [x] `pyproject.toml` - Added `tenacity>=9.0.0`

### 2. Configuration Files
- [x] `Procfile` - Split into `worker_default`, `worker_spotify`, and `worker_leaderboard`
- [x] `Dockerfile` - Updated CMD to start all three workers
- [x] `docker-compose.yml` - Created with proper service separation

### 3. Documentation
- [x] `SPOTIFY_RATE_LIMITING.md` - Architecture documentation
- [x] `DOCKER_DEPLOYMENT.md` - Docker-specific deployment guide
- [x] `test_spotify_worker.py` - Testing script

## 🚀 Deployment Steps

### For Railway/Render (Single Container)

1. **Push Changes**
   ```bash
   git add .
   git commit -m "Add Spotify rate limiting with dedicated worker queue"
   git push
   ```

2. **Verify Environment Variables**
   Ensure these are set in your dashboard:
   - `REDIS_URL`
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`

3. **Deploy**
   - Railway/Render will auto-deploy from Git
   - The `Dockerfile` CMD starts all processes automatically

4. **Verify Deployment**
   Check logs for these lines:
   ```
   Starting RQ worker listening on queues: ['default']
   Starting RQ worker listening on queues: ['spotify']
   *** Listening on spotify...
   *** Listening on default...
   ```

### For Heroku (Multi-Dyno)

1. **Push Changes**
   ```bash
   git push heroku main
   ```

2. **Scale Dynos**
   ```bash
   heroku ps:scale worker_default=1 worker_spotify=1 worker_leaderboard=1
   ```

3. **Verify**
   ```bash
   heroku ps
   # Should show:
   # web.1: up
   # worker_default.1: up
   # worker_spotify.1: up
   # worker_leaderboard.1: up
   ```

### For Docker Compose (Local/VPS)

1. **Build and Start**
   ```bash
   docker-compose up --build -d
   ```

2. **Verify All Services**
   ```bash
   docker-compose ps
   # All services should show "Up (healthy)" or "Up"
   ```

3. **Check Logs**
   ```bash
   docker-compose logs -f worker_spotify
   docker-compose logs -f worker_default
   docker-compose logs -f worker_leaderboard
   ```

## 🔍 Post-Deployment Verification

### 1. Test Spotify Search

```bash
# Test the search endpoint
curl "https://your-domain.com/api/v1/search?query=Taylor+Swift"

# Should return albums (may take 50-150ms longer than before)
```

### 2. Check Redis Queue

If you have Redis access:
```bash
redis-cli
> LLEN rq:queue:spotify
> LLEN rq:queue:default
> KEYS rq:worker:*
```

### 3. Monitor for Rate Limits

Watch application logs for these patterns:

**✅ Good (Retry working):**
```
[SPOTIFY WORKER] Executing method: search_artist_albums
Retrying ... attempt 2 (429 Too Many Requests)
[SPOTIFY WORKER] Successfully completed: search_artist_albums
```

**❌ Bad (Multiple workers):**
```
429 Client Error: Too Many Requests
429 Client Error: Too Many Requests (multiple rapid occurrences)
```

If you see multiple 429s, check scaling!

### 4. Test Worker Proxy

Use the test script:
```bash
# Locally
uv run python test_spotify_worker.py

# In Docker
docker-compose exec web python test_spotify_worker.py
```

## ⚠️ Critical Warnings

### NEVER Scale Spotify Worker Beyond 1

**Railway/Render:**
- ✅ Scale by adding more containers (each has 1 Spotify worker)
- ❌ Don't modify the Dockerfile CMD to start multiple Spotify workers

**Heroku:**
```bash
# ✅ Correct
heroku ps:scale worker_spotify=1

# ❌ WRONG - breaks rate limiting
heroku ps:scale worker_spotify=2
```

**Docker Compose:**
```bash
# ✅ Correct
docker-compose up

# ❌ WRONG - breaks rate limiting
docker-compose up --scale worker_spotify=2
```

## 📊 Expected Performance

### Before (Direct API Calls)
- Search latency: 200-400ms
- Risk: 429 errors with 4+ concurrent users
- Retries: Per-worker (not coordinated)

### After (Worker Queue)
- Search latency: 250-500ms (+50-150ms overhead)
- Risk: Zero 429 errors (serialized through 1 worker)
- Retries: Coordinated via tenacity with exponential backoff

## 🐛 Troubleshooting

### Issue: "Spotify worker timed out"

**Cause:** Worker not running or overloaded

**Fix:**
1. Check logs: `docker-compose logs worker_spotify`
2. Verify Redis connection: `docker-compose exec redis redis-cli ping`
3. Check queue backlog: `redis-cli LLEN rq:queue:spotify`
4. Restart worker: `docker-compose restart worker_spotify`

### Issue: Still getting 429 errors

**Cause:** Multiple Spotify workers running

**Fix:**
1. Check scaling: `docker-compose ps` or `heroku ps`
2. Verify only 1 worker_spotify is running
3. Kill extra workers if found
4. Restart deployment with correct scaling

### Issue: Searches are very slow (>1s)

**Cause:** Queue backlog or network issues

**Fix:**
1. Check queue length: `redis-cli LLEN rq:queue:spotify`
2. If >10 jobs queued, consider investigating slow requests
3. Check worker logs for timeout errors
4. Verify Spotify API status: https://status.spotify.com/

## 📝 Rollback Plan

If issues occur:

1. **Quick Fix (Disable Worker Proxy):**
   ```python
   # In app/api/v1/search.py, temporarily revert to direct calls:
   results = await spotify_client.search_artist_albums(query, client)
   # Instead of:
   # results = await spotify_client.call_via_worker("search_artist_albums", ...)
   ```

2. **Full Rollback:**
   ```bash
   git revert HEAD
   git push
   ```

3. **Emergency (Heroku):**
   ```bash
   heroku releases:rollback
   ```

## ✨ Success Criteria

- [ ] Spotify search works (returns results)
- [ ] No 429 errors in logs after 1 hour of production traffic
- [ ] Both workers (`default` and `spotify`) are running
- [ ] Worker logs show "Listening on spotify..." and "Listening on default..."
- [ ] Queue lengths stay low (< 5 jobs at any time)
- [ ] Search latency is acceptable (< 500ms for most requests)

## 📞 Support

If you encounter issues:

1. Check logs first
2. Review `SPOTIFY_RATE_LIMITING.md` for architecture details
3. Review `DOCKER_DEPLOYMENT.md` for deployment specifics
4. Verify environment variables are set correctly
5. Check Redis connectivity

---

**Date Deployed:** _________

**Deployed By:** _________

**Notes:** _________
