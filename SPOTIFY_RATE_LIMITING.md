# Spotify API Integration

## Overview

Spotify API calls are made directly from the web process for maximum performance. Rate limiting is handled via automatic retries with exponential backoff using the `tenacity` library.

## Architecture

```
┌─────────────────┐
│  Gunicorn Web   │  (4 workers)
│   (async calls) │
└────────┬────────┘
         │
         │  Direct async HTTP calls
         │  with automatic retries
         ▼
┌─────────────────┐
│  Spotify API    │
└─────────────────┘
```

## Rate Limiting Strategy

Instead of serializing all requests through a single worker (which creates a bottleneck under load), we use:

1. **Retry Logic**: Uses `tenacity` to automatically retry on:
   - `429 Too Many Requests`
   - `5xx` server errors
   - Connection timeouts

2. **Exponential Backoff**: Waits 2s, 4s, up to 30s between retries

3. **Concurrent Requests**: Multiple users can make Spotify API calls simultaneously

This approach provides:
- **Low latency**: No Redis queue overhead (~100-200ms savings per request)
- **High throughput**: Concurrent requests instead of serial processing
- **Resilience**: Automatic retries handle transient rate limits

## Configuration

### Environment Variables

```bash
# Required for Spotify integration
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

## Usage in Code

```python
from app.clients.spotify import spotify_client

# Direct async calls
albums = await spotify_client.search_artist_albums(query)
tracks = await spotify_client.get_album_tracks(spotify_id)
artists = await spotify_client.search_artists_only(query)
```

## References

- **Tenacity (Retry Library)**: https://tenacity.readthedocs.io/
- **Spotify API Rate Limits**: https://developer.spotify.com/documentation/web-api/concepts/rate-limits
