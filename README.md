# SongRanker Backend

FastAPI backend for the SongRanker application.

## API Specification Sync

To keep the frontend API client up to date, we maintain an `openapi.json` file in the `songranker-frontend` directory.

### Automation
A "skill" for AI agents is defined in `.skill-api-sync.md`. Whenever the API structure changes, the following script must be run:

```bash
./scripts/sync_api.sh
```

This script:
1. Extracts the OpenAPI schema from the FastAPI app.
2. Saves it to `../songranker-frontend/openapi.json`.
