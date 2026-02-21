---
date: 2026-02-20
topic: apple-music-integration-playlist-first
supersedes:
  - docs/plans/2026-02-17-feat-switch-primary-metadata-source-to-apple-music-plan.md
  - docs/brainstorms/2026-02-19-viral-music-imports-brainstorm.md
---

# Apple Music Integration & Playlist-First Reboot

## What We're Building

A unified feature that does three things in one cohesive release:

1. **Apple Music backend client** (`app/clients/apple_music.py`) — mirrors `SpotifyClient` in structure. Handles ES256 JWT auth, artist/album search, tracklist fetch, and **playlist import** via the Apple Music Catalog API. Public playlist links only (no MusicKit JS / user OAuth).

2. **Apple Music as primary search source** — replaces Spotify as the Fast Path for artist/album search (`GET /search`, `GET /suggest`, `GET /tracks/{id}`). Spotify and LastFM/MusicBrainz become fallbacks.

3. **Playlist-first frontend** — the landing page becomes a single prominent "paste a link" input that accepts both Spotify and Apple Music playlist URLs. Artist/album search remains as a secondary option below it.

This supersedes both the standalone Apple Music search migration plan (2026-02-17) and the Spotify-only viral imports brainstorm (2026-02-19), merging them into a single coherent delivery.

## Why This Approach

The two prior plans were heading in the same direction from different angles. Merging them eliminates redundant work and delivers a consistent story: Apple Music is the primary platform, Spotify is a supported import source, and playlists are the main entry point. The public-link-only constraint for Apple Music keeps the backend simple (server-side token only, no per-user OAuth) and matches the existing "no-login" Spotify approach.

## Key Decisions

- **Public playlist links only (both platforms)**: No MusicKit JS / user OAuth. Both Spotify and Apple Music imports use server-side tokens. Users can only import public playlists. This maximizes simplicity and preserves the "no-login" viral funnel.
- **Apple Music as primary, Spotify as fallback**: `GET /search` and `GET /suggest` hit Apple Music first. If Apple Music credentials are absent or return empty, falls back to Spotify → LastFM/MusicBrainz chain.
- **ISRC-first cross-platform deduplication**: Apple Music catalog tracks include ISRCs. Spotify tracks already populate `isrc` in the session. ISRC is the canonical key; normalized title+artist fuzzy match is the fallback. Consistent with the existing songs table schema.
- **Unified import endpoint**: A single `POST /imports/playlist` endpoint detects platform from the URL (spotify.com vs. music.apple.com) and routes to the appropriate client. No separate endpoint for Apple Music.
- **JWT rotation at 24 hours**: Apple allows up to 6-month tokens, but a 24-hour cycle limits blast radius. Token is cached as a singleton and regenerated on expiry — same pattern as Spotify's access token.
- **Frontend: single link input, primary**: A large paste input on the landing page. Platform auto-detected from URL. Artist/album search demoted to a secondary "Or search by artist" section below.
- **Apple Developer credentials**: Requires Team ID, Key ID, and a `.p8` private key from the Apple Developer portal (MusicKit enabled). Obtaining and configuring these is a prerequisite step in the plan.

## Credential Setup (Apple Developer Prerequisites)

To get the required Apple Music API credentials:
1. Sign in to [developer.apple.com](https://developer.apple.com) → **Certificates, Identifiers & Profiles**
2. Go to **Keys** → **+** (Create a new key)
3. Name it (e.g., "SongRanker MusicKit"), check **MusicKit**, and click **Continue** → **Register**
4. Download the `.p8` file immediately (only available once)
5. Note the **Key ID** shown on the key detail page
6. Your **Team ID** is shown in the top-right corner of the developer portal (10-character string)

These become `APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_TEAM_ID`, and `APPLE_MUSIC_SECRET_KEY` (the `.p8` file content with `\n`-escaped newlines) in `.env`.

## Scope Summary

### Backend
- `app/clients/apple_music.py` — new client (search, tracks, playlist import, JWT auth)
- `app/core/config.py` — add Apple Music config vars
- `app/api/v1/search.py` — swap primary source to Apple Music
- `app/api/v1/imports.py` — update to handle both Spotify and Apple Music playlist URLs
- `app/schemas/session.py` — ensure `source_platform` enum includes `"apple_music"`

### Frontend
- Landing page: prominent paste-link input replaces artist search as primary
- Platform auto-detection from URL (Spotify vs. Apple Music)
- Artist/album search as secondary option
- Playlist session UI: show playlist name, cover art, and owner/source badge

## Open Questions

- **Apple Music playlist URL format**: Catalog playlists use `music.apple.com/us/playlist/{name}/{id}` — the ID starts with `pl.`. Curated/editorial playlists use a different ID format. Need to verify the API supports fetching both via `/v1/catalog/{storefront}/playlists/{id}`.
- **Frontend repo**: This brainstorm is captured in the backend repo. The frontend changes (landing page redesign) will need a corresponding plan in the frontend repo. Confirm frontend repo path/name before planning.

## Resolved Questions

- **Import method**: Public links only. No MusicKit JS / user library access.
- **Cross-platform key**: ISRC-first, title+artist fuzzy fallback.
- **Plan consolidation**: This supersedes the 2026-02-17 Apple Music search plan and the 2026-02-19 Spotify-only imports plan.
- **Apple credentials**: Developer account exists; credentials need to be extracted (see prerequisite steps above).
- **Frontend primary UX**: Single paste input, platform auto-detected, artist search demoted to secondary.
- **Storefront for playlist import**: Parse from URL (e.g., `us` from `music.apple.com/us/playlist/...`). More accurate than always using server default.
- **Rate limit retry strategy**: Same tenacity config as Spotify — 3 attempts, exponential backoff (2–30s), retry only on 429 and 5xx.

## Next Steps
→ `/workflows:plan` for implementation details
