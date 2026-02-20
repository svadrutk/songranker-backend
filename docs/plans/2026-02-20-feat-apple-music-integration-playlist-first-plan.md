---
title: Apple Music Integration & Playlist-First Reboot
type: feat
status: active
date: 2026-02-20
supersedes:
  - docs/plans/2026-02-17-feat-switch-primary-metadata-source-to-apple-music-plan.md
  - docs/plans/2026-02-19-feat-viral-music-imports-plan.md
brainstorm: docs/brainstorms/2026-02-20-apple-music-integration-playlist-first-brainstorm.md
---

# Apple Music Integration & Playlist-First Reboot

## Enhancement Summary

**Deepened on:** 2026-02-20
**Agents used:** security-sentinel, performance-oracle, best-practices-researcher, architecture-strategist, spec-flow-analyzer

### Key Research Corrections Applied

1. **Key storage** — Changed from `\n`-escaped newlines to base64-encoded `APPLE_MUSIC_PRIVATE_KEY_B64`. The PEM `-----BEGIN PRIVATE KEY-----` dashes break `flyctl secrets set` and other CLI tooling. Base64 is universally safe.

2. **Playlist pagination** — Changed from `?include=tracks` (hard-capped at 100 tracks per Apple staff) to the dedicated `/tracks` sub-endpoint with offset pagination. This is the critical correctness fix — without it, playlists with >100 tracks would be silently truncated.

3. **Artist search** — Changed from single-step search (`types=albums`, limit 25) to two-step artist-ID → albums approach (up to 100 albums across 4 pages). Mirrors the existing Spotify client pattern exactly and gives complete discographies for prolific artists.

4. **Key validation at config load** — `apple_music_configured` now validates the decoded key is a valid EC P-256 private key via `cryptography`, not just that the string is non-empty. Catches wrong key type (e.g., RSA pasted by mistake) at startup.

5. **`isCompilation` check order** — Must be first in `_get_release_type`. Otherwise a 12-track compilation is misclassified as "Album".

6. **`is_spotify_id` regex fix** — Added lookahead `(?=.*[A-Za-z])` requiring at least one letter. Prevents a 22-digit Apple Music ID from being misrouted to Spotify.

7. **JWT `headers` dict** — Removed `"alg"` from `headers=` dict in `jwt.encode()`. PyJWT overrides `algorithm=` with `headers["alg"]` if both present — confusing and fragile.

8. **Parallel metadata + tracks fetch** — Added `asyncio.gather` in `imports.py`. Free ~60–80ms improvement with zero implementation cost.

9. **401 error handling in search fallback** — Apple Music `401` errors log at `ERROR` level and do not silently fall through to Spotify. A 401 indicates broken credentials and must alert operators, not hide behind Spotify results.

10. **Transient 404 retries** — Apple Music API is known to return intermittent 404s due to infrastructure instability (confirmed by Apple staff). Added 404 to the retry predicate (alongside 429 and 5xx).

---

## Overview

This feature merges two prior active plans into one cohesive delivery:

1. **Apple Music backend client** — `app/clients/apple_music.py`, mirroring `SpotifyClient`. ES256 JWT auth (24-hour rotation), catalog search, album tracklist fetch, and playlist import.
2. **Apple Music as primary search source** — `GET /search` and `GET /suggest` hit Apple Music first; Spotify and LastFM/MusicBrainz are fallbacks.
3. **Unified playlist import** — `POST /imports/playlist` auto-detects platform from the URL (Spotify vs. Apple Music). Public playlists only; no user OAuth.
4. **Playlist-first frontend** — The landing page is redesigned around a single paste-a-link input. Artist/album search is demoted to a secondary option.

**Key constraints decided in brainstorm:**
- Public links only — no MusicKit JS / user library OAuth
- ISRC-first cross-platform deduplication
- Storefront parsed from Apple Music URL (not hardcoded)
- Retry on 429, 5xx, **and transient 404s** (Apple infrastructure known to return transient 404s)
- JWT rotated every 24 hours

**Research-confirmed corrections (applied throughout this plan):**
- **Key transport**: Use base64-encoded key (`APPLE_MUSIC_PRIVATE_KEY_B64`) — the `\n`-escape approach breaks silently on Fly.io and other hosting platforms due to `-----` dashes in PEM headers
- **Playlist pagination**: Use `GET /v1/catalog/{sf}/playlists/{id}/tracks` (dedicated endpoint) not `?include=tracks` relationship — the embedded relationship is hard-capped at 100 tracks per Apple staff confirmation
- **Artist search**: Use two-step artist-ID → albums approach (mirrors Spotify) to get up to 100 albums, not 25
- **Transient 404s**: Apple Music infrastructure returns intermittent 404s that are not real "not found" errors — retry these
- **`isCompilation` check**: Must be first in release type classification
- **`is_spotify_id` fix**: Tighten to require at least one letter (regex), preventing a 22-digit AM ID from being misrouted
- **`alg` in JWT headers dict**: Remove it — PyJWT sets it from the `algorithm=` parameter; having both is confusing
- **Metadata + tracks parallel fetch**: Use `asyncio.gather` in imports.py — saves ~60–80ms per import

---

## Problem Statement / Motivation

The app currently uses Spotify as the only fast-path metadata source and only supports Spotify playlists for import. Apple Music has a richer catalog API, returns ISRCs natively, and is the preferred platform for the intended user base. Keeping Spotify as the primary search source creates unnecessary coupling. Additionally, the current UX leads with artist/album search — a friction-heavy flow vs. a direct "paste your playlist and rank" experience.

---

## Apple Developer Credential Setup (Prerequisites)

Before implementation can be tested, Apple Music API credentials must be obtained:

1. Sign in to [developer.apple.com](https://developer.apple.com) → **Certificates, Identifiers & Profiles**
2. Click **Keys** → **+** (Create a new key)
3. Name it (e.g., "SongRanker MusicKit"), enable **MusicKit**, click **Continue** → **Register**
4. **Download the `.p8` file immediately** — it cannot be re-downloaded
5. Note the **Key ID** shown on the key detail page (10-char string like `XYZ1234567`)
6. Find your **Team ID** in the top-right corner of the developer portal (10-char string like `ABCDE12345`)

The `.p8` file contains a PEM-encoded EC private key. **Store it base64-encoded** (see Config section) — the `\n`-escape approach breaks silently on Fly.io because the `-----BEGIN PRIVATE KEY-----` dashes are parsed as CLI flags.

```bash
# Encode the key once (macOS/Linux):
base64 -i AuthKey_XXXXXXXXXX.p8 | tr -d '\n'
# Copy the output — that's APPLE_MUSIC_PRIVATE_KEY_B64 in your .env
```

---

## Technical Approach

### Architecture

All changes follow the existing **Metadata Provider Pattern**: external API clients are singletons in `app/clients/`, orchestrated by route handlers. No new architectural layers are introduced.

**Fallback chain for `GET /search`:**
```
Apple Music (primary) → Spotify (secondary) → LastFM + MusicBrainz (canonical fallback)
```

**Platform detection for `POST /imports/playlist`:**
```
URL contains "music.apple.com" → AppleMusicClient
URL contains "spotify.com"      → SpotifyClient
```

**Track ID routing for `GET /tracks/{id}`:**
```
Pure numeric string  → Apple Music catalog album
22-char alphanumeric → Spotify album
UUID (MBID)          → LastFM + MusicBrainz
```

---

## Implementation Phases

### Phase 1: Foundation — Config & Dependencies

**Files:**
- `app/core/config.py`
- `pyproject.toml`
- `.env.example`

**Tasks:**

#### 1.1 Add Apple Music config fields (`app/core/config.py`)

Insert after line 17 (after `SPOTIFY_CLIENT_SECRET`):

```python
# Apple Music
APPLE_MUSIC_TEAM_ID: str = ""
APPLE_MUSIC_KEY_ID: str = ""
# Store .p8 content as BASE64 (single-line). Encode with: base64 -i AuthKey_xxx.p8 | tr -d '\n'
# This avoids CLI parsing failures with PEM dashes on Fly.io and similar platforms.
APPLE_MUSIC_PRIVATE_KEY_B64: SecretStr = SecretStr("")
APPLE_MUSIC_STOREFRONT: str = "us"
```

Add a computed property after the fields:

```python
@property
def apple_music_configured(self) -> bool:
    """True only when all three Apple Music credential fields are non-empty and valid."""
    if not (
        self.APPLE_MUSIC_TEAM_ID.strip()
        and self.APPLE_MUSIC_KEY_ID.strip()
        and self.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value().strip()
    ):
        return False
    # Validate the decoded key parses as a valid EC P-256 private key
    try:
        import base64
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey, SECP256R1
        raw = base64.b64decode(self.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value())
        key = load_pem_private_key(raw, password=None)
        return isinstance(key, EllipticCurvePrivateKey) and isinstance(key.curve, SECP256R1)
    except Exception:
        return False
```

Add `from pydantic import SecretStr` to the imports.

**Why validate the key in `apple_music_configured`?** A malformed or wrong-type key (e.g., RSA key pasted by mistake) will fail at JWT signing time during a live request, not at startup. Validating here catches misconfigurations early and makes `apple_music_configured` reliable as a feature flag.

#### 1.2 Add explicit dependency (`pyproject.toml`)

`PyJWT[crypto]` and `cryptography` are already in `uv.lock` as transitive dependencies. Make them explicit:

```toml
"PyJWT[crypto]>=2.10.1",
"cryptography>=46.0.0",
```

#### 1.3 Update `.env.example`

Add the four new Apple Music vars:

```
APPLE_MUSIC_TEAM_ID=
APPLE_MUSIC_KEY_ID=
APPLE_MUSIC_PRIVATE_KEY_B64=
APPLE_MUSIC_STOREFRONT=us
```

Also add the missing Spotify and Redis vars that are currently absent from `.env.example`:

```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
REDIS_URL=redis://localhost:6379/0
```

---

### Phase 2: Apple Music Client

**File:** `app/clients/apple_music.py` (new)

The client mirrors `SpotifyClient` exactly in structure. Singleton instance at module bottom.

#### 2.1 JWT generation

```python
_TOKEN_LIFETIME = 86400    # 24 hours (Apple max is ~6 months; 24h is good security hygiene)
_TOKEN_REFRESH_BUFFER = 300  # Regenerate 5 min before expiry

def _generate_jwt(self) -> str:
    """Generate a cached ES256 developer token. Rotates every 24 hours."""
    if self._token and time.time() < (self._token_expires_at - self._TOKEN_REFRESH_BUFFER):
        return self._token

    import base64
    raw_key = base64.b64decode(settings.APPLE_MUSIC_PRIVATE_KEY_B64.get_secret_value())
    private_key_pem = raw_key.decode("utf-8")
    
    now = int(time.time())
    
    token = jwt.encode(
        {
            "iss": settings.APPLE_MUSIC_TEAM_ID,
            "iat": now,
            "exp": now + self._TOKEN_LIFETIME,
        },
        private_key_pem,
        algorithm="ES256",
        headers={"kid": settings.APPLE_MUSIC_KEY_ID},  # alg is set by algorithm= param
    )
    # PyJWT 2.x always returns str; no isinstance guard needed
    self._token = token
    self._token_expires_at = now + self._TOKEN_LIFETIME
    return self._token
```

**Key notes:**
- JWT generation is synchronous (no network call, ~0.2ms for ES256) — no `async` needed
- Base64 key decode: `base64.b64decode(b64_string)` → bytes → decode UTF-8 → PEM string
- `algorithm="ES256"` enforces the algorithm at the `jwt.encode` level; **do not** also put `"alg"` in `headers=` (PyJWT would override `algorithm=` with `headers["alg"]` — confusing and fragile)
- No `isinstance(token, str)` guard — PyJWT 2.x always returns `str`; the guard is dead code

#### 2.2 HTTP request pattern

Mirror the `@retry` decorator from `spotify.py:51-61`, **extended to also retry transient 404s** (Apple Music infrastructure is known to return intermittent 404s that are not real "not found" errors):

```python
@staticmethod
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    # Retry on: 429 (rate limit), 5xx (server errors), 404 (Apple's transient infra bug)
    # Never retry: 400 (bad request — our bug), 401 (bad JWT — config error), 403 (private/unauthorized)
    retry=retry_if_exception(
        lambda e: isinstance(e, httpx.HTTPStatusError)
                  and (
                      e.response.status_code == 429
                      or e.response.status_code == 404
                      or e.response.status_code >= 500
                  )
    ),
    reraise=True,
)
async def _get_request(
    active_client: httpx.AsyncClient,
    token: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response = await active_client.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    response.raise_for_status()
    return response.json()
```

**Why retry 404?** Apple staff have confirmed on the developer forums that the Apple Music API returns intermittent 404s due to infrastructure instability — the same request succeeds minutes later. After 3 retries, a persistent 404 is surfaced as a real "not found" error.

**Note:** The token parameter is the JWT Bearer token, not an OAuth access token.

#### 2.2b Error handling in search fallback chain (`search.py`)

When Apple Music raises a `401 Unauthorized` (bad JWT / misconfigured credentials), this must **not** silently fall through to Spotify. A 401 means the credentials are broken — masking it in the fallback would make deployments with bad AM keys look healthy (Spotify results returned, no errors logged). Handle it explicitly:

```python
# In search.py fast-path block:
if settings.apple_music_configured:
    try:
        cache_key = f"am_search:{norm_query}"
        results = await cache.get_or_fetch(...)
        if results:
            return results
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error(
                "Apple Music JWT rejected (401). Check APPLE_MUSIC_TEAM_ID, "
                "APPLE_MUSIC_KEY_ID, and APPLE_MUSIC_PRIVATE_KEY_B64. "
                "Falling back to Spotify."
            )
        else:
            logger.warning(f"Apple Music search failed ({e.response.status_code}), falling back.")
    except Exception as e:
        logger.warning(f"Apple Music search error: {e}, falling back.")
    # Fall through to Spotify regardless
```

#### 2.3 Methods to implement

| Method | Apple Music Endpoint | Notes |
|---|---|---|
| `search_artist_albums(artist_name, storefront="us")` | Two-step: `GET /search?types=artists` → `GET /artists/{id}/albums` (paginated, up to 4 pages) | Returns `List[Dict]` matching `ReleaseGroupResponse` shape. Two-step mirrors Spotify for completeness (up to 100 albums vs. search cap of 25). |
| `search_artists_only(query, storefront="us")` | `GET /v1/catalog/{sf}/search?types=artists&limit=5` | Returns `List[str]` (5 names) |
| `get_album_tracks(album_id, storefront="us")` | `GET /v1/catalog/{sf}/albums/{id}?include=tracks` then paginate `next` if >100 tracks | Returns `List[str]` (clean track names) |
| `get_playlist_metadata(playlist_id, storefront)` | `GET /v1/catalog/{sf}/playlists/{id}` | Returns `{name, curator, image_url}` |
| `get_playlist_tracks(playlist_id, storefront, limit=250)` | `GET /v1/catalog/{sf}/playlists/{id}/tracks?limit=100` paginated via `next` cursor | Returns `List[Dict]` with ISRC, apple_music_id, etc. **Uses dedicated `/tracks` sub-endpoint, not `?include=tracks`** |
| `_process_albums(albums, artist_name)` | — | Dedup + type classification |
| `_get_release_type(attributes)` | — | Static method, see classification logic |
| `_resolve_artwork(artwork_dict, size=500)` | — | Static method, `{w}x{h}` → `500x500` |

#### 2.4 Release type classification

```python
@staticmethod
def _get_release_type(attributes: Dict[str, Any]) -> str:
    # isCompilation MUST be checked first — a 12-track compilation would otherwise
    # be misclassified as "Album"
    if attributes.get("isCompilation", False):
        return "Compilation"
    
    track_count = attributes.get("trackCount", 0)
    is_single = attributes.get("isSingle", False)
    name = attributes.get("name", "").lower()

    if is_single or track_count <= 3:
        return "Single"
    if 4 <= track_count <= 6 or " - ep" in name:
        return "EP"
    return "Album"
```

**Order matters:** `isCompilation` is checked first. A compilation with 12 tracks would otherwise fall through to "Album", which is incorrect.

#### 2.5 `_process_albums` output shape

Must match the existing `ReleaseGroupResponse` shape plus `source` field:

```python
{
    "id": str,          # Apple Music numeric catalog ID
    "title": str,       # attributes.name
    "artist": str,      # attributes.artistName
    "type": str,        # "Album" | "EP" | "Single" | "Compilation"
    "cover_art": {
        "front": True,
        "url": str | None   # resolved 500x500 URL
    },
    "source": "apple_music"
}
```

#### 2.6 `get_playlist_tracks` output shape

Must be compatible with `SongInput` and `dedupe_tracks_for_selection()`:

```python
{
    "name": str,
    "artist": str,
    "album": str | None,          # attributes.albumName
    "isrc": str | None,           # attributes.isrc
    "duration_ms": int,           # attributes.durationInMillis
    "cover_url": str | None,      # resolved 300x300 artwork URL
    "apple_music_id": str | None, # data[].id (numeric string)
    "spotify_id": None,           # always None for AM tracks
    "genres": List[str],          # attributes.genreNames
    "popularity": int,            # track index (0-based, as proxy for curation order)
}
```

**Popularity proxy:** Apple Music doesn't have a popularity score. Use the track's 0-based index in the playlist as a proxy (`len(all_tracks)` before appending). This gives `select_anchor_variance_quick_rank()` something to sort by (earlier in playlist = higher curation prominence = "anchor" candidate).

**ISRC availability:** Apple Music returns `attributes.isrc` for `songs` type resources. A small percentage (~2–5%) of tracks — music videos, unmatched user uploads — have no ISRC. These are acceptable; `SongInput.isrc` is already `Optional[str]`.

#### 2.7 Artwork URL resolution

```python
@staticmethod
def _resolve_artwork(artwork: Dict[str, Any], size: int = 500) -> Optional[str]:
    url = artwork.get("url")
    if not url:
        return None
    # Replace {w}x{h} template — handle URLs that may not have template vars
    return url.replace("{w}", str(size)).replace("{h}", str(size))
```

#### 2.8 Playlist pagination

**Critical:** Use the **dedicated `/tracks` sub-endpoint** for pagination. Apple Music's `?include=tracks` relationship expansion is hard-capped at 100 tracks and the `next` cursor in `relationships.tracks` is unreliable for pagination (confirmed by Apple staff on developer forums). For playlists with >100 tracks:

```python
# CORRECT: Dedicated relationship endpoint supports full pagination
url = f"{self.base_url}/v1/catalog/{storefront}/playlists/{playlist_id}/tracks"
params = {"limit": 100}
while url and len(all_tracks) < limit:
    data = await self._get(url, params=params if not all_tracks else None)
    tracks = data.get("data", [])
    # Filter: only process type="songs" — music videos have no ISRC and can't be ranked
    for t in tracks:
        if t.get("type") != "songs":
            continue
        # ... process track
    next_path = data.get("next")  # Full relative URL with offset already embedded
    url = f"{self.base_url}{next_path}" if next_path else None

# WRONG (do not use for pagination):
# GET /v1/catalog/{sf}/playlists/{id}?include=tracks
# → Hard cap of 100 tracks; adding limit= param causes 400 error
```

**Track type filter:** Only process `type == "songs"` items. Music videos (`type == "music-videos"`) embedded in playlists have no ISRC and cannot be ranked. Skip them with a log at `DEBUG` level.

#### 2.9 Module-level singleton

```python
apple_music_client = AppleMusicClient()
```

The client reads credentials from `settings` internally (same pattern as `spotify_client`).

#### 2.10 Startup validation in `app/main.py`

In the `lifespan()` context manager, add a credential check:

```python
# Validate Apple Music credentials at startup
if not settings.apple_music_configured:
    logger.warning(
        "Apple Music credentials incomplete (APPLE_MUSIC_TEAM_ID, APPLE_MUSIC_KEY_ID, "
        "APPLE_MUSIC_PRIVATE_KEY must all be set). Apple Music features are disabled."
    )
```

This surfaces misconfiguration early without crashing the server.

---

### Phase 3: Utility & Schema Updates

**Files:**
- `app/core/utils.py`
- `app/schemas/session.py`

#### 3.1 Fix `is_spotify_id` and add `is_apple_music_id` (`app/core/utils.py`, lines 25–27)

**Bug:** The current `is_spotify_id` check (`len == 22 and no "-" and no ":"`) would match a 22-digit all-numeric string, which is a valid Apple Music ID format. This creates a routing collision risk as Apple Music's ID space grows.

**Fix `is_spotify_id`** (line 25):
```python
import re

_SPOTIFY_ID_RE = re.compile(r'^(?=.*[A-Za-z])[A-Za-z0-9]{22}$')

def is_spotify_id(resource_id: str) -> bool:
    """Check if the ID looks like a Spotify ID (22 Base62 chars, must contain at least one letter)."""
    return bool(_SPOTIFY_ID_RE.match(resource_id))
```

The lookahead `(?=.*[A-Za-z])` requires at least one letter, making a pure-digit 22-char string unambiguously an Apple Music ID, not a Spotify ID.

**Add `is_apple_music_id`** (after `is_spotify_id`):
```python
def is_apple_music_id(resource_id: str) -> bool:
    """Check if the ID looks like an Apple Music catalog ID (pure numeric string)."""
    return resource_id.isdigit()
```

Apple Music catalog album/track IDs are pure numeric strings (e.g., `"1440935467"`). Playlist IDs (`pl.xxx`) are handled separately in the import flow and never reach this function.

**Routing order in `get_tracks`:** Always check `is_apple_music_id` before `is_spotify_id` — pure digits are unambiguously AM; the Spotify regex now requires a letter, so there's no overlap.

#### 3.2 Add `apple_music_id` to schemas (`app/schemas/session.py`)

In `SongInput` (after existing `spotify_id` field at line ~9):

```python
apple_music_id: Optional[str] = None
```

In `SessionSong` (after existing `spotify_id` field):

```python
apple_music_id: Optional[str] = None
```

This is a non-breaking additive change. `source_platform` is already `Optional[str]` — no code change needed; just document `"apple_music"` as a valid value.

#### 3.3 Update `_track_key()` in `app/core/track_selection.py`

The deduplication key priority chain should include `apple_music_id`:

```python
# Current: ISRC → spotify_id → (title, artist)
# Updated: ISRC → spotify_id → apple_music_id → (title, artist)
```

Find the `_track_key()` function (or equivalent dedup logic) and add `apple_music_id` after `spotify_id` in the priority chain.

#### 3.4 Update `_decide_canonical()` in `app/core/deduplication.py`

The canonical song selection currently scores by `spotify_id` presence. Add equal weight to `apple_music_id`:

```python
# Score apple_music_id equally to spotify_id
score += 1 if song.get("apple_music_id") else 0
```

This prevents Apple Music-sourced tracks from always losing deduplication battles against Spotify tracks for the same song.

---

### Phase 4: Search API Update

**File:** `app/api/v1/search.py`

#### 4.1 Add imports (top of file)

```python
from app.clients.apple_music import apple_music_client
```

And add `is_apple_music_id` to the existing `utils` import line.

#### 4.2 Replace the fast-path block (currently lines 174–186)

Replace the Spotify-only fast path with the new AM → Spotify → fallback chain:

```python
# FAST PATH 1: Apple Music (primary)
# Use longer TTL (6h) — Apple Music catalog data is very stable
if settings.apple_music_configured:
    try:
        cache_key = f"am_search:{norm_query}"
        results = await cache.get_or_fetch(
            cache_key,
            lambda: apple_music_client.search_artist_albums(query),
            ttl_seconds=21600,   # 6 hours (vs. Spotify's 1 hour — AM catalog is stable)
            swr_ttl_seconds=86400,
            background_tasks=background_tasks,
        )
        if results:
            return results
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.error(
                "Apple Music JWT rejected (401). Check credentials. Falling back to Spotify."
            )
        else:
            logger.warning(
                f"Apple Music search failed ({e.response.status_code}), falling back to Spotify."
            )
    except Exception as e:
        logger.warning(f"Apple Music search error: {e}, falling back to Spotify.")

# FAST PATH 2: Spotify (secondary fast path, unchanged logic)
if settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET:
    cache_key = f"spotify_search:{norm_query}"
    results = await cache.get_or_fetch(
        cache_key,
        lambda: spotify_client.search_artist_albums(query),
        ttl_seconds=3600,
        background_tasks=background_tasks,
    )
    if results:
        return results

# FALLBACK: LastFM + MusicBrainz (unchanged)
```

**Key decisions:**
- **Separate cache keys** (`am_search:` vs. `spotify_search:`) prevent cross-contamination when enabling/disabling AM
- **6-hour TTL for AM** vs. 1 hour for Spotify — Apple Music catalog data is extremely stable; this reduces API calls by ~6x for popular artists
- **Explicit error handling** for `401` (credential error — log at `ERROR` to alert operators) vs. other errors (log at `WARNING` and fall through gracefully)

#### 4.3 Update `_get_artist_suggestions` (lines ~216–235)

Add Apple Music suggest before Spotify:

```python
# Apple Music suggest (primary)
if settings.apple_music_configured:
    cache_key = f"am_suggest:{norm_query}"
    names = await cache.get_or_fetch(
        cache_key,
        lambda: apple_music_client.search_artists_only(query),
        ttl_seconds=14400,
        background_tasks=background_tasks,
    )
    if names:
        return [ArtistSuggestion(name=n) for n in names]

# Spotify suggest (secondary)
if settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET:
    # ... existing Spotify suggest logic unchanged
```

#### 4.4 Update `get_tracks` endpoint (lines ~315–319)

Add Apple Music branch before Spotify:

```python
# Apple Music album ID (pure numeric string)
if is_apple_music_id(release_group_id):
    logger.info(f"Apple Music ID detected: {release_group_id}")
    cache_key = f"am_tracks:{release_group_id}"
    return await cache.get_or_fetch(
        cache_key,
        lambda: apple_music_client.get_album_tracks(release_group_id),
        ttl_seconds=86400,
        background_tasks=background_tasks,
    )

# Spotify album ID (22-char alphanumeric)
if is_spotify_id(release_group_id):
    logger.info(f"Spotify ID detected: {release_group_id}")
    # Note: skip _resolve_mbid_background for Apple Music results
    # (no MBID bridging needed per plan)
    if artist and title:
        background_tasks.add_task(_resolve_mbid_background, artist, title, release_group_id, client)
    return await spotify_client.get_album_tracks(release_group_id)

# MBID → LastFM + MusicBrainz (unchanged)
```

**Note:** The `_resolve_mbid_background` task is only triggered for Spotify IDs. Apple Music IDs do not go through MBID bridging (per brainstorm decision).

---

### Phase 5: Import API Update

**File:** `app/api/v1/imports.py`

#### 5.1 Add import

```python
from app.clients.apple_music import apple_music_client
```

#### 5.2 Add Apple Music URL extractor (after `extract_spotify_playlist_id`)

```python
import re
from urllib.parse import urlparse

def extract_apple_music_playlist_info(url: str) -> tuple[Optional[str], str]:
    """
    Extract (playlist_id, storefront) from a public Apple Music playlist URL.
    
    Handles:
      https://music.apple.com/us/playlist/my-playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde
      https://music.apple.com/us/playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde (no slug)
    
    Returns (playlist_id, storefront), or (None, "us") if no match.
    """
    # Match storefront + pl. ID; slug between playlist/ and pl. is optional
    pattern = r"music\.apple\.com/([a-z]{2})/playlist/(?:[^/]+/)?(pl\.[a-f0-9]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(2), match.group(1)
    return None, "us"
```

**URL variations handled:**
- `music.apple.com/us/playlist/my-name/pl.abc123` (standard)
- `music.apple.com/us/playlist/pl.abc123` (no slug)
- Query params (`?app=music`, `?si=...`) are ignored by the regex

#### 5.3 Platform detection block (replace current lines 34–36)

```python
# Detect platform from URL
url_lower = import_data.url.lower()
if "music.apple.com" in url_lower:
    platform = "apple_music"
    playlist_id, storefront = extract_apple_music_playlist_info(import_data.url)
    if not playlist_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_APPLE_MUSIC_URL", "message": "Could not extract a valid Apple Music playlist ID from the URL. Ensure it is a public playlist link."}
        )
    if not settings.apple_music_configured:
        raise HTTPException(
            status_code=503,
            detail={"code": "APPLE_MUSIC_NOT_CONFIGURED", "message": "Apple Music integration is not configured on this server."}
        )
else:
    # Default: Spotify
    platform = "spotify"
    storefront = None
    playlist_id = extract_spotify_playlist_id(import_data.url)
    if not playlist_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SPOTIFY_URL", "message": "Could not extract a valid Spotify playlist ID from the URL."}
        )
```

#### 5.4 Branch the fetch logic

The existing `try` block fetches metadata and tracks unconditionally from Spotify. Split into a platform-aware branch, and **fetch metadata and tracks in parallel** (saves ~60–80ms per import):

```python
try:
    if platform == "apple_music":
        # Parallel fetch — metadata and tracks are independent requests
        metadata, raw_tracks = await asyncio.gather(
            apple_music_client.get_playlist_metadata(playlist_id, storefront),
            apple_music_client.get_playlist_tracks(
                playlist_id, storefront, limit=import_data.limit or 250
            ),
        )
    else:
        metadata, raw_tracks = await asyncio.gather(
            spotify_client.get_playlist_metadata(playlist_id, client=http_client),
            spotify_client.get_playlist_tracks(
                playlist_id, limit=import_data.limit or 250, client=http_client
            ),
        )
except httpx.HTTPStatusError as e:
    # After retries, a persistent 404/403 means the playlist is truly private or deleted
    if e.response.status_code in (403, 404):
        raise HTTPException(
            status_code=404,
            detail={"code": "PLAYLIST_NOT_FOUND_OR_PRIVATE", "message": "Playlist not found or is private."}
        )
    raise HTTPException(
        status_code=502,
        detail={"code": "UPSTREAM_API_ERROR", "message": f"Error fetching from {platform}."}
    )
```

Add `import asyncio` at the top of `imports.py`.

#### 5.5 Unified track mapping to `SongInput`

After fetching `raw_tracks`, map both Spotify and Apple Music to a unified `SongInput`. The existing Spotify mapping can serve as the template — Apple Music tracks already match the `SongInput` shape (see Phase 2.6):

```python
songs = [
    SongInput(
        name=t["name"],
        artist=t["artist"],
        album=t.get("album"),
        isrc=t.get("isrc"),
        spotify_id=t.get("spotify_id"),
        apple_music_id=t.get("apple_music_id"),
        genres=t.get("genres", []),
        cover_url=t.get("cover_url"),
    )
    for t in raw_tracks
    if t.get("name") and t.get("artist")
]
```

#### 5.6 Fix: always run deduplication before rank selection

**Bug (GAP-11):** The existing `rank_all` path skips `dedupe_tracks_for_selection()`, so playlists with duplicate tracks create duplicate songs in the session. Fix this for both platforms simultaneously:

```python
# Always deduplicate first, regardless of rank_mode
songs = dedupe_tracks_for_selection(songs)

if not songs:
    raise HTTPException(
        status_code=404,
        detail={"code": "PLAYLIST_NO_RANKABLE_TRACKS", "message": "No rankable tracks found."}
    )

if import_data.rank_mode == "quick_rank":
    selected_songs, strategy = select_anchor_variance_quick_rank(songs)
else:
    selected_songs = songs[:250]  # cap at 250 for rank_all
    strategy = None
```

#### 5.7 Pass `source_platform` dynamically

```python
# Was: source_platform="spotify"
# Now:
source_platform=platform,   # "spotify" or "apple_music"
```

Also add `storefront` to `collection_metadata` for Apple Music sessions:

```python
collection_metadata={
    "owner": metadata.get("owner") or metadata.get("curator"),
    "image_url": metadata.get("image_url"),
    "rank_mode": import_data.rank_mode,
    "quick_rank_strategy": strategy,
    **({"storefront": storefront} if platform == "apple_music" else {}),
}
```

#### 5.8 Generalize error codes

| Old code | New code |
|---|---|
| `SPOTIFY_PLAYLIST_NOT_FOUND_OR_PRIVATE` | `PLAYLIST_NOT_FOUND_OR_PRIVATE` |
| `SPOTIFY_API_ERROR` | `UPSTREAM_API_ERROR` |
| `SPOTIFY_PLAYLIST_NO_RANKABLE_TRACKS` | `PLAYLIST_NO_RANKABLE_TRACKS` |

---

### Phase 6: Database Schema

**Migration required:** Add `apple_music_id` column to the `songs` table in Supabase.

```sql
ALTER TABLE songs ADD COLUMN IF NOT EXISTS apple_music_id TEXT;
CREATE INDEX IF NOT EXISTS idx_songs_apple_music_id ON songs (apple_music_id);
```

**`source_platform` check:** Confirmed to be `Optional[str]` (free text, not a DB enum). No migration needed — `"apple_music"` is already a valid value.

Run this migration against the Supabase project via the dashboard SQL editor or Supabase CLI before deploying.

---

### Phase 7: Tests

**File:** `test_apple_music_client.py` (new, at repo root, matching existing test file convention)

Use `unittest.IsolatedAsyncioTestCase` for async tests (Python 3.8+, available in 3.13).

```python
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

class TestAppleMusicReleaseTypeClassification(unittest.TestCase):
    def test_single_by_is_single_flag(self): ...
    def test_single_by_track_count(self):    # 1-3 tracks
    def test_ep_by_track_count(self):        # 4-6 tracks
    def test_ep_by_name(self):               # " - ep" in name
    def test_album_by_track_count(self):     # 7+ tracks
    def test_compilation_flag(self): ...

class TestArtworkResolution(unittest.TestCase):
    def test_resolves_template_url(self):    # {w}x{h} → 500x500
    def test_handles_missing_url(self):      # None artwork dict
    def test_handles_url_without_template(self): # URL with no template vars

class TestPlaylistURLParsing(unittest.TestCase):
    def test_standard_url(self):             # /us/playlist/name/pl.abc
    def test_url_without_slug(self):         # /us/playlist/pl.abc
    def test_url_with_query_params(self):    # /us/playlist/name/pl.abc?app=music
    def test_invalid_url_returns_none(self): ...

class TestAppleMusicClientAsync(unittest.IsolatedAsyncioTestCase):
    async def test_jwt_cached_on_reuse(self): ...
    async def test_jwt_regenerated_on_expiry(self): ...
    async def test_search_artist_albums_maps_correctly(self): ...  # mock _get_request
    async def test_get_playlist_tracks_paginates(self): ...
    async def test_get_playlist_tracks_respects_limit(self): ...
    async def test_404_raises_http_status_error(self): ...
```

**File:** `test_imports_platform_detection.py` (new, at repo root)

```python
class TestImportsPlatformDetection(unittest.IsolatedAsyncioTestCase):
    async def test_spotify_url_routes_to_spotify(self): ...
    async def test_apple_music_url_routes_to_apple_music(self): ...
    async def test_invalid_url_returns_400(self): ...
    async def test_apple_music_not_configured_returns_503(self): ...
    async def test_private_playlist_returns_404(self): ...
    async def test_rank_all_deduplicates_before_selection(self): ...  # regression for GAP-11
```

---

## Acceptance Criteria

### Functional Requirements

- [ ] Searching for an artist returns albums/EPs from Apple Music when credentials are configured
- [ ] Searching falls back to Spotify when Apple Music returns empty or is unconfigured
- [ ] Searching falls back to LastFM+MusicBrainz when both Apple Music and Spotify are unconfigured
- [ ] Album artwork URLs are resolved to 500×500 concrete URLs (no `{w}x{h}` placeholders in responses)
- [ ] Release classification correctly identifies Singles (≤3 tracks or `isSingle=true`), EPs (4–6 tracks or `" - ep"` in name), Albums (≥7 tracks), Compilations (`isCompilation=true`)
- [ ] `POST /imports/playlist` accepts a valid Apple Music public playlist URL and returns a session
- [ ] `POST /imports/playlist` accepts a valid Spotify playlist URL and returns a session (regression)
- [ ] `POST /imports/playlist` returns 400 for an unrecognized URL format
- [ ] `POST /imports/playlist` returns 404 for a private/deleted playlist (Apple Music 403/404 mapped to app 404)
- [ ] `POST /imports/playlist` returns 503 when Apple Music URL is provided but credentials are not configured
- [ ] `GET /tracks/{id}` returns tracks for a numeric Apple Music album ID
- [ ] `GET /tracks/{id}` continues to return tracks for Spotify IDs and MBIDs (regression)
- [ ] ISRCs from Apple Music tracks are stored in the `songs` table and used for deduplication
- [ ] Apple Music playlist sessions have `source_platform="apple_music"` and include `storefront` in `collection_metadata`
- [ ] Both `quick_rank` and `rank_all` modes deduplicate tracks before creating a session
- [ ] `apple_music_id` is stored in session songs for Apple Music-sourced tracks
- [ ] `GET /suggest` returns artist suggestions from Apple Music when configured

### Non-Functional Requirements

- [ ] **Security:** Apple Music private key is stored as `SecretStr` and never appears in logs
- [ ] **Security:** JWT uses `algorithm="ES256"` explicitly to prevent algorithm confusion
- [ ] **Performance:** Search p95 latency < 300ms (cached path)
- [ ] **Resilience:** Apple Music API calls retry up to 3 times on 429/5xx with exponential backoff
- [ ] **Resilience:** JWT is regenerated automatically before expiry (5-minute safety buffer)
- [ ] **Resilience:** Partial/missing Apple Music credentials logged as `WARNING` at startup, not crash
- [ ] **Observability:** All Apple Music API calls log at `INFO` level with the endpoint and response time

---

## Dependencies & Risks

| Dependency | Status | Notes |
|---|---|---|
| `PyJWT[crypto]>=2.10.1` | ✅ In `uv.lock` | Make explicit in `pyproject.toml` |
| `cryptography>=46.0.0` | ✅ In `uv.lock` | Make explicit in `pyproject.toml` |
| Apple Developer account w/ MusicKit | ✅ Exists | `.p8` key needs to be extracted and base64-encoded (see Prerequisites) |
| Supabase migration (`apple_music_id` column) | ❌ Pending | Run before deployment |
| Apple Music `pl.` IDs on catalog endpoint | ✅ Confirmed | `GET /v1/catalog/{sf}/playlists/{pl.xxx}` works per Apple docs and third-party confirmation |
| Apple Music `/tracks` sub-endpoint for pagination | ✅ Confirmed | Recommended by Apple staff; `?include=tracks` hard-capped at 100 |

| Risk | Severity | Mitigation |
|---|---|---|
| Malformed `.p8` key (wrong format, wrong curve) | High | `apple_music_configured` validates key type/curve via `cryptography` library at startup |
| Base64 encoding error (trailing newlines in output) | Medium | Use `base64 -i file.p8 \| tr -d '\n'` — `tr -d '\n'` is required |
| Apple Music infrastructure transient 404/5xx | Medium | Retry decorator includes 404 in addition to 5xx; 3 attempts with exponential backoff |
| Apple Music rate limits (undocumented, ~20 req/s) | Medium | Tenacity retry (3 attempts, exponential backoff on 429 and 5xx) |
| `is_spotify_id` routing collision with 22-digit AM ID | Low | Fixed by requiring at least one letter in Spotify ID regex |
| Track not available in storefront | Low | ISRC dedup still works cross-storefront; skip missing tracks |
| Music videos in playlists (no ISRC) | Low | Filter `type != "songs"` in `get_playlist_tracks` |

---

## References & Research

### Internal References

- `app/clients/spotify.py` — pattern to mirror exactly for `apple_music.py`
- `app/api/v1/search.py:174–186` — fast-path block to replace
- `app/api/v1/search.py:315–319` — `get_tracks` ID routing to extend
- `app/api/v1/imports.py:21–36` — URL extraction and platform detection to generalize
- `app/core/config.py:15–17` — Spotify config block; Apple Music fields go after
- `app/core/utils.py:25–27` — `is_spotify_id`; add `is_apple_music_id` after
- `app/schemas/session.py:5–12` — `SongInput`; add `apple_music_id` field
- `app/core/track_selection.py` — `_track_key()` priority chain to extend
- `app/core/deduplication.py` — `_decide_canonical()` scoring to extend

### External References

- [Apple Music API Reference](https://developer.apple.com/documentation/applemusicapi/)
- [Generating Developer Tokens (ES256 JWT)](https://developer.apple.com/documentation/applemusicapi/generating_developer_tokens)
- [Catalog Playlists endpoint](https://developer.apple.com/documentation/applemusicapi/get_a_catalog_playlist)
- [Catalog Search endpoint](https://developer.apple.com/documentation/applemusicapi/search_for_catalog_resources)
- [PyJWT ES256 documentation](https://pyjwt.readthedocs.io/en/stable/usage.html#encoding-decoding-tokens-with-es256-ecdsa)

### Related Plans

- Superseded: `docs/plans/2026-02-17-feat-switch-primary-metadata-source-to-apple-music-plan.md`
- Superseded: `docs/plans/2026-02-19-feat-viral-music-imports-plan.md`
- Brainstorm: `docs/brainstorms/2026-02-20-apple-music-integration-playlist-first-brainstorm.md`
