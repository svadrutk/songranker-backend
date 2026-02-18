---
title: Switch primary metadata source to Apple Music
type: feat
status: active
date: 2026-02-17
---

# Switch primary metadata source to Apple Music

## Overview

This feature involves replacing Spotify as the primary "Fast Path" metadata provider with Apple Music. The backend currently uses Spotify for high-speed artist search and tracklist retrieval. We will implement a new `AppleMusicClient` using the Apple Music API (MusicKit) and update the search orchestration logic to prioritize Apple Music results.

## Enhancement Summary

**Deepened on:** 2026-02-18
**Sections enhanced:** 5
**Research agents used:** framework-docs-researcher, performance-oracle, security-sentinel, architecture-strategist

### Key Improvements
1.  **Deeper Categorization Logic**: Precise logic for distinguishing Singles, EPs, and Albums using `isSingle` and `trackCount`.
2.  **Performance Optimization**: Use of `include=tracks` relationship expansion to prevent N+1 queries during tracklist retrieval.
3.  **Security Hardening**: Recommendations for JWT rotation (24-hour cycle) and use of `SecretStr` for sensitive `.p8` key storage.
4.  **Simplified Architecture**: Decision to treat Apple Music as the primary source of truth, reducing complexity by deprecating background MusicBrainz ID bridging for Apple Music results.

## Problem Statement / Motivation

Spotify is currently the primary source for metadata gathering because of its speed and excellent typo handling. However, the project requirements have shifted to prefer Apple Music's catalog and metadata structure. We need to maintain the "Fast Path" performance (sub-300ms searches) while transitioning to Apple Music.

## Proposed Solution

1.  **Implement `AppleMusicClient`**: A new client in `app/clients/apple_music.py` that handles authentication via ES256 JWT, searching the Apple Music catalog, and fetching tracklists.
2.  **Update Configuration**: Add `APPLE_MUSIC_TEAM_ID`, `APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_SECRET_KEY`, and `APPLE_MUSIC_STOREFRONT` to `app/core/config.py`.
3.  **Update Search API**: Modify `app/api/v1/search.py` to use `apple_music_client` instead of `spotify_client` as the primary search engine.
4.  **Data Mapping**: Map Apple Music's nested JSON structure (e.g., `attributes`) to the project's standardized `ReleaseGroupResponse` and `TrackResponse` models.

## Technical Approach

### Architecture: The Metadata Provider Pattern

We will continue the existing pattern where external APIs are encapsulated in client classes and orchestrated by the search router.

#### Research Insights

**Best Practices:**
- **Primary Source Strategy**: Treat Apple Music as the "Source of Truth" for the Fast Path. If an Apple Music ID is present, we will prioritize its metadata over fallbacks.
- **Relationship Expansion**: Use the `include=tracks` parameter in catalog requests to fetch album metadata and tracklists in a single round-trip, significantly reducing latency.

**Performance Considerations:**
- **JWT Singleton**: Implement JWT generation as a cached property. Signing ES256 is CPU-intensive; rotate the token every 24 hours rather than per-request.
- **Storefront Awareness**: Catalog results vary by storefront. Ensure the `APPLE_MUSIC_STOREFRONT` (default: `us`) is correctly handled in all requests.

### 1. New Client: `app/clients/apple_music.py`

The client will implement:
- **`_generate_jwt()`**: Generates a signed ES256 JWT for authentication.
- **`search_artist_albums(artist_name: str)`**: Maps to `/v1/catalog/{storefront}/search?types=albums,songs`.
- **`get_album_tracks(album_id: str)`**: Maps to `/v1/catalog/{storefront}/albums/{id}/tracks`.
- **`_process_albums()`**: Handles deduplication and title normalization.

#### Research Insights

**Release Classification Logic:**
Apple Music returns all releases as `type: "albums"`. We will apply the following categorization logic:
- **Single**: If `attributes.isSingle` is `true` OR `trackCount` is 1-3.
- **EP**: If `attributes.isSingle` is `false` AND `trackCount` is 4-6.
- **Album**: If `trackCount` is 7 or more.
- **Fallback**: Check if the name ends with ` - EP` for certain 1-3 track EPs with long durations.

**Implementation Details:**
```python
# Precise categorization logic
def get_release_type(attributes):
    track_count = attributes.get("trackCount", 0)
    is_single = attributes.get("isSingle", False)
    name = attributes.get("name", "").lower()
    
    if is_single or track_count <= 3:
        return "Single"
    if 4 <= track_count <= 6 or " - ep" in name:
        return "EP"
    return "Album"
```

### 2. Authentication (JWT)

#### Research Insights

**Security Considerations:**
- **Secret Management**: Store the `.p8` private key content as a `SecretStr` in Pydantic settings. Avoid multi-line formatting issues in `.env` by using escaped newlines (`\n`).
- **Algorithm Enforcement**: Explicitly enforce `algorithm="ES256"` in `jwt.encode()` to prevent algorithm confusion attacks.
- **Short-lived Tokens**: While Apple allows 6 months, a 24-hour rotation cycle reduces the blast radius of a leaked token.

### 3. Data Mapping Details

| Spotify Field | Apple Music Equivalent | Mapping Logic |
| :--- | :--- | :--- |
| `album.name` | `attributes.name` | Direct mapping |
| `album.images[0].url` | `attributes.artwork.url` | Replace `{w}x{h}` with `600x600` |
| `track.duration_ms` | `attributes.durationInMillis` | Direct mapping |
| `track.name` | `attributes.name` | Direct mapping |
| `album_type` | Calculated field | See "Release Classification Logic" above |

#### Research Insights

**Edge Cases:**
- **Artwork Template**: Some Apple Music artwork URLs use `{f}` for format. Ensure the replacement logic is robust.
- **Storefront Mismatch**: If a user provides an ID from a different storefront than the server's default, the API may return a 404. We will log these occurrences to monitor for regionality issues.

## Implementation Phases

### Phase 1: Foundation (JWT & Config)
- Update `app/core/config.py` with Apple Music settings.
- Implement JWT generation logic using `PyJWT`.
- **Estimated Effort**: Small

### Phase 2: Core Client (Search & Tracks)
- Create `app/clients/apple_music.py`.
- Implement `search_artist_albums` and `get_album_tracks` (using `include=tracks`).
- Implement classification logic.
- **Estimated Effort**: Medium

### Phase 3: Integration & Migration
- Update `app/api/v1/search.py` to prioritize Apple Music.
- Deprecate `_resolve_mbid_background` for Apple Music sources to simplify the pipeline.
- Update `is_spotify_id` to include `is_apple_music_id` detection.
- **Estimated Effort**: Medium

## Acceptance Criteria

### Functional Requirements
- [ ] Searching for an artist returns a list of albums and EPs from Apple Music.
- [ ] Album artwork is correctly displayed using the templated URL (600x600).
- [ ] Classification correctly identifies Singles vs EPs vs Albums.
- [ ] Fetching tracks for an Apple Music album returns a clean list of track titles.
- [ ] Authentication token is refreshed automatically on a 24-hour cycle.

### Non-Functional Requirements
- [ ] **Security**: Private key is masked in logs and stored as `SecretStr`.
- [ ] **Performance**: 95th percentile latency for search < 300ms.
- [ ] **Resilience**: Client handles `429 Too Many Requests` by respecting the `Retry-After` header.

## Dependencies & Risks
- **Dependency**: `PyJWT[crypto]` (requires `cryptography`).
- **Risk**: Storefront regionality may lead to "missing" content if the server storefront doesn't match the user's expectation.
- **Risk**: Deprecating MBID bridging means Apple Music results will not be unified with existing MusicBrainz-based rankings unless titles match perfectly.

## References & Research
- [Apple Music API Reference](https://developer.apple.com/documentation/applemusicapi/)
- [JWT ES256 Guidelines](https://developer.apple.com/documentation/applemusicapi/generating_developer_tokens)
- [Spotify API Mapping (Current)](app/clients/spotify.py)
- [Search Router (Current)](app/api/v1/search.py)
