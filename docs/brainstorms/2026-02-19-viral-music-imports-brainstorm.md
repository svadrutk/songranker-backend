---
date: 2026-02-19
topic: viral-music-imports
---

# Viral Music Imports & "Link-to-Rank" (Playlist Edition)

## What We're Building
We are evolving the app from a single-artist ranker into a flexible **Playlist Ranker**. The core feature is a **"Crate" Import Flow** where users can instantly start a ranking duel by:
1. Pasting a public **Spotify Playlist URL** (handled via Client Credentials Flow).
2. Connecting their **Apple Music Library** or pasting an Apple Music playlist link (via MusicKit JS).
3. Ranking any group of songs, regardless of whether they belong to one artist or many.

The goal is to move from "Playlist/Artist Link" to "Ranking Duel" in under 60 seconds, allowing users to settle debates like "What's the best track on this soundtrack?" or "Rank my 'On Repeat' list."

## Why This Approach
The "Single Artist" constraint was too limiting for casual listeners and fandoms who want to rank specific vibes, eras, or curated playlists. By shifting to a **Playlist-First** architecture, we unlock massive viral potential (e.g., ranking a "Best of 2026" or "Era's Tour Setlist" playlist). This approach leverages the user's existing "curation" to provide an immediate, personalized ranking experience.

## Key Decisions
- **Unified "Playlist" Context**: The app will treat every session as a "Playlist," whether it's a generated one (from an artist's discography) or an imported one (from Spotify/Apple Music).
- **No-Login Spotify Imports**: For public playlists, we will use server-side tokens to fetch tracks. This eliminates the "Login with Spotify" bounce rate.
- **Apple Music Priority**: Since Apple Music is more open in 2026, it will be the primary high-fidelity sync option for private libraries.
- **Multi-Artist Analytics**: The analytics page will be updated to show "Top Artists" and "Genre Breakdown" within the ranked playlist, not just individual song stats.
- **Default "Quick Rank" (Top 50)**: By default, we suggest ranking the top 50 songs of an import to keep it fast, with a "Rank All" toggle for completionists.

## Resolved Questions
- **Multi-Artist Handling**: The app will now natively support multi-artist rankings. The "Artist Name" in the UI will be replaced by the "Playlist Name" for these sessions.
- **Receipt Branding**: Share cards will include a "Source" badge (e.g., "Imported from Apple Music") to celebrate the platform and add visual flair.

## Open Questions
- **Deduplication Logic**: Does the current fuzzy-matching deduplication still make sense for multi-artist playlists, or is it only needed for single-artist discographies?
- **Global Leaderboards**: How do we aggregate "Global Rankings" if the playlists are all different? (e.g., Should we have a global "Top 100" based on every ranking ever done?)
- **Spotify Private Playlists**: Since we're avoiding User OAuth for Spotify to stay viral, how do we explain to users that they can only import *public* playlists?

## Next Steps
→ `/workflows:plan` for implementation details
