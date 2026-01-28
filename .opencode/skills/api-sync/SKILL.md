# Skill: API Specification Sync

## Context
The SongRanker project consists of a FastAPI backend and a Next.js frontend. To keep the frontend synchronized with backend API changes, an OpenAPI specification must be exported to the frontend directory.

## Trigger
Whenever you modify:
1. `app/main.py` (adding/removing routers or middleware)
2. Files in `app/api/` (changing endpoints, request/response models)
3. Any Pydantic models used in API schemas.

## Action
Run the sync script from the `songranker-backend` directory:
```bash
./scripts/sync_api.sh
```

## Verification
Ensure `/Users/svadrut/Documents/songranker-app/songranker-frontend/openapi.json` has been updated with your changes.
