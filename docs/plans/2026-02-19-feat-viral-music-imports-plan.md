---
title: Viral Music Imports & "Link-to-Rank" (Playlist Edition)
type: feat
status: active
date: 2026-02-19
---

# Viral Music Imports & "Link-to-Rank" (Playlist Edition)

## Enhancement Summary

**Deepened on:** 2026-02-19
**Sections enhanced:** 5
**Research agents used:** best-practices-researcher, performance-oracle, security-sentinel

### Key Improvements
1.  **"Anchor & Variance" Quick Rank**: Implemented a sophisticated "Top 50" selection logic using a 30/20 split between high-popularity "anchors" and random "wildcards" to accelerate algorithmic convergence.
2.  **ISRC-First Deduplication**: Shifted to ISRC as the primary data integrity key to enable cross-platform song matching and unified global leaderboards.
3.  **Collection-Agnostic Schema**: Generalized the session model using a `collection_metadata` JSONB structure, future-proofing the app for albums, charts, and custom sets beyond playlists.
4.  **Convergence-Aware UX**: Integrated a 90% stability threshold (Top 10 lookback) to proactively trigger the "Viral Share" state.

## Overview

This feature evolves the application from a single-artist ranker into a flexible **Playlist Ranker**. The core enhancement is a **"Crate" Import Flow** that allows users to instantly start a ranking duel by pasting a public **Spotify** playlist URL. This shift requires generalizing the backend architecture from artist-centric sessions to playlist-centric ones, enabling multi-artist rankings and viral shareable analytics (Receipts/Wrapped style).

## Problem Statement / Motivation

The current "Single Artist" constraint limits the app's appeal for users who want to rank curated collections, soundtracks, or personal "On Repeat" lists. Additionally, the "Login with Spotify" requirement creates friction for casual users. We need a "No-Login" path for public playlists to maximize virality and a unified data model that supports multi-artist sessions.

## Proposed Solution

1.  **"No-Login" Import Flow**: Use Server-to-Server tokens (Spotify Client Credentials) to fetch public playlist metadata and tracks without requiring user OAuth.
2.  **Playlist-Centric Architecture**:
    *   Add `playlist_id`, `playlist_name`, and `source_platform` to the `sessions` table (migrating to a `collection_metadata` JSONB for future flexibility).
    *   Generalize database queries to support multi-artist duels and analytics.
3.  **"Quick Rank" vs. "Rank All"**:
    *   **Default**: **Top 40** (by playlist order/popularity). This is the "Sweet Spot" for a single session, aiming for ~150-200 total interactions (including wins, skips, and ties) to reach a stable Top 10.
    *   **Option**: **Rank All** (capped at 250 tracks). For playlists > 40, users can explicitly choose to rank the full set, with the understanding that it is a multi-session effort.
4.  **Viral Share Cards**: Generate high-fidelity "Receipt" or "Spotify Wrapped" style images showing Top Artists, Top Genres, and the final ranking.

## Technical Approach

### Architecture: From Artist-Centric to Collection-Centric

The system currently groups songs and comparisons by `artist`. We will introduce a `playlist_id` (UUID) as a primary session identifier, utilizing a **`collection_metadata` JSONB** for additional context.

#### Research Insights

**Ranking Efficiency & Fatigue:**
- **Empirical Data**: For small sets (~20 songs), convergence typically requires ~70 duels. 
- **The "Wall"**: UX research shows user fatigue and "speed-clicking" sets in after 60-100 duels. In music ranking, where "mental playback" or skips/ties are frequent, the effective limit is lower.
- **The 40-Song Sweet Spot**: A 40-song set requires ~$O(40 \log 40) \approx 210$ duels for full convergence. This aligns with the upper limit of a "high-intent" user session once skips and ties (zero-information events) are factored in.
- **Milestones**: A stable Top 5 is reached much faster (~50-70 duels), providing early dopamine hits for the user.

**Performance & Scaling (250-Item Limits):**
- **Convergence**: For $n=250$, theoretical stability is reached at ~2,000 duels ($O(n \log n)$). Our **"Smart Pairing" (pairing-v2)** approach with Uncertainty Sampling and Adjacent Ranking is optimized to reach this point faster.
- **Bottlenecks**: Bradley-Terry math on 250 items is trivial (~20ms). Primary bottleneck is **DB I/O**.
- **Update Frequency**: Bradley-Terry scores and stability metrics are updated every 5 duels (controlled by the frontend). The backend provides the necessary endpoints to persist and compute these updates. Update time for 250 items is ~300ms total.

#### 1. Backend Clients (`app/clients/`)

*   **`SpotifyClient` Enhancements**:
    *   Implement `get_playlist_tracks(playlist_id: str)` using the `/v1/playlists/{id}/tracks` endpoint.
    *   Use `fields` filtering to minimize payload: `items(track(name,isrc,popularity,artists(name),duration_ms,album(images))),total,next`.
    *   Handle pagination (100 items per page) up to the 250-track cap.

#### 2. Database Schema Changes (`Supabase`)

*   **`sessions` Table**:
    *   `playlist_id`: UUID (nullable for single-artist legacy sessions).
    *   `playlist_name`: Text.
    *   `collection_metadata`: JSONB (contains extra info like owner, image URL, and `source_platform`).
    *   `source_platform`: Enum (`spotify`, `manual`).
*   **`songs` Table**:
    *   **`isrc`**: Text (Primary deduplication key; used for `on_conflict` in upserts).
    *   `genres`: Text Array (fetched from Artist metadata on Spotify).
*   **RPC Generalization**:
    *   Update `get_artist_comparisons` to `get_collection_comparisons(artist_id, playlist_id)` to allow aggregating wins across different session types.

#### 3. Ranking & Analytics Logic

*   **Bradley-Terry Convergence**: The `RankingManager` already supports arbitrary lists of `song_ids`. We will set a **90% stability threshold** (measured by Top 10 lookback) to trigger the "Share Receipt" prompt.
*   **Multi-Artist Analytics**: A new endpoint `GET /sessions/{id}/analytics` will return:
    *   `top_artists`: Frequency of artists in the top 10% of the ranking.
    *   `genre_breakdown`: Aggregated genres from the ranked songs.

### Implementation Phases

#### Phase 1: Foundation (Database & Shared Logic)
- [x] Add `playlist_id` and metadata columns to `sessions`.
- [x] Update `Session` and `Track` Pydantic models to support multi-artist data.
- **Estimated Effort**: Small

#### Phase 2: Spotify Client Enhancements
- [x] Implement `get_playlist_tracks` in `SpotifyClient` (Client Credentials).
- [x] Add URL parsing logic to identify Spotify playlists and extract IDs.
- **Estimated Effort**: Small

#### Phase 3: "Fast Path" Import API
- Create `POST /v1/imports/playlist` endpoint.
- Logic: Fetch -> Filter (Unavailable/Duplicates) -> Bulk Upsert Songs -> Create Session.
- Implement "Quick Rank" (Top 50) logic.
- **Estimated Effort**: Medium

#### Phase 4: Viral Share & Polishing
- Implement "Receipt" and "Wrapped" image generation using `Playwright` or a dedicated SVG-to-PNG service.
- Update frontend to handle "Playlist Name" instead of "Artist Name" in the UI header.
- **Estimated Effort**: Large

## Acceptance Criteria

### Functional Requirements
- [x] Users can paste a Spotify playlist URL and see a preview (Name, Count, Covers).
- [x] "No-Login" flow successfully fetches tracks for public Spotify playlists.
- [ ] "Quick Rank" correctly selects the Top 40 tracks for high-intent ranking sessions.
- [ ] Ranking UI displays the correct Artist/Title for each song in multi-artist sessions.
- [ ] Users can generate and download a "Receipt" share card upon completing a ranking.

### Non-Functional Requirements
- [ ] **Performance**: Playlist fetch and session creation should take < 3 seconds for 100 tracks.
- [ ] **Resilience**: Handle 404 (Private) Spotify playlists with a clear error message and "How to make public" guide.
- [ ] **Scalability**: Cap "Rank All" at 250 tracks to prevent browser/DB performance degradation.

## Risk Analysis & Mitigation
- **Risk**: Spotify Rate Limits (429 errors).
  - *Mitigation*: Implement caching for playlist metadata (1-hour TTL) and use `tenacity` for retries with exponential backoff. Use `limit` and `offset` carefully for pagination.
- **Risk**: Duplicate Songs (Same song on different albums).
  - *Mitigation*: **ISRC-First Strategy**. Use ISRC as the primary key for deduplication. Fallback to `normalized_title + primary_artist` if ISRC is missing.
- **Risk**: Private Playlists.
  - *Mitigation*: Detect `404 Not Found` as a potential "Private" signal. Show a clear UI state for "Private Playlist Detected" with a help guide on toggling public visibility.
- **Risk**: Convergence Overhead.
  - *Mitigation*: The frontend controls the update frequency (default: every 5 duels). If performance degrades on large (250+) sets, the frontend can be configured to increase the update interval to every 10 or 20 duels.
- **Risk**: Artist-Centric UI Mismatch.
  - *Mitigation*: Introduce `display_name` in API responses that defaults to `playlist_name` or `collection_metadata['name']` for multi-artist sessions.

## References & Research
- [Spotify Playlist API Docs](https://developer.spotify.com/documentation/web-api/reference/get-playlists-tracks)
- [Brainstorm: Viral Music Imports](docs/brainstorms/2026-02-19-viral-music-imports-brainstorm.md)
- [Learnings: Receiptify/Wrapped UI Patterns](https://receiptify.herokuapp.com/)
