"""
Tests for the imports endpoint platform detection and Apple Music / Spotify import flow.

Includes:
 - Unit tests for URL parsing helpers
 - Integration tests that hit real Spotify + Apple Music APIs and create real sessions
"""

import unittest

from app.api.v1.imports import extract_apple_music_playlist_info, extract_spotify_playlist_id
from app.core.track_selection import dedupe_tracks_for_selection


# ---------------------------------------------------------------------------
# Unit tests — URL parsers
# ---------------------------------------------------------------------------

class TestExtractSpotifyPlaylistId(unittest.TestCase):
    def test_standard_url(self):
        result = extract_spotify_playlist_id(
            "https://open.spotify.com/playlist/76aXSma1pw1efuiOE9cv6R?si=abc"
        )
        self.assertEqual(result, "76aXSma1pw1efuiOE9cv6R")

    def test_url_without_query(self):
        result = extract_spotify_playlist_id(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        self.assertEqual(result, "37i9dQZF1DXcBWIGoYBM5M")

    def test_invalid_url_returns_none(self):
        self.assertIsNone(extract_spotify_playlist_id("https://open.spotify.com/track/abc"))
        self.assertIsNone(extract_spotify_playlist_id("https://music.apple.com/us/playlist/pl.abc"))


class TestExtractAppleMusicPlaylistInfo(unittest.TestCase):
    def test_standard_url(self):
        pid, sf = extract_apple_music_playlist_info(
            "https://music.apple.com/us/playlist/my-playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde"
        )
        self.assertEqual(pid, "pl.cb4d1c09a2df4230a78d0395fe1f8fde")
        self.assertEqual(sf, "us")

    def test_gb_storefront(self):
        pid, sf = extract_apple_music_playlist_info(
            "https://music.apple.com/gb/playlist/name/pl.abc123def456"
        )
        self.assertEqual(sf, "gb")

    def test_url_without_slug(self):
        pid, sf = extract_apple_music_playlist_info(
            "https://music.apple.com/us/playlist/pl.f4d106fed2bd41149aaacabb233eb5eb"
        )
        self.assertEqual(pid, "pl.f4d106fed2bd41149aaacabb233eb5eb")

    def test_url_with_query_params(self):
        pid, sf = extract_apple_music_playlist_info(
            "https://music.apple.com/us/playlist/today/pl.f4d106fed2bd41149aaacabb233eb5eb?app=music"
        )
        self.assertEqual(pid, "pl.f4d106fed2bd41149aaacabb233eb5eb")

    def test_spotify_url_returns_none(self):
        pid, sf = extract_apple_music_playlist_info(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        self.assertIsNone(pid)
        self.assertEqual(sf, "us")  # default


# ---------------------------------------------------------------------------
# Unit test — dedup regression (GAP-11: rank_all must dedup)
# ---------------------------------------------------------------------------

class TestDeduplicationAlwaysRuns(unittest.TestCase):
    def test_dedups_by_isrc(self):
        tracks = [
            {"name": "Song A", "artist": "Artist", "isrc": "USAT12345678", "popularity": 80},
            {"name": "Song A (Remaster)", "artist": "Artist", "isrc": "USAT12345678", "popularity": 60},
            {"name": "Song B", "artist": "Artist", "isrc": "USAT87654321", "popularity": 50},
        ]
        deduped = dedupe_tracks_for_selection(tracks)
        self.assertEqual(len(deduped), 2)
        # Should keep the higher-popularity version
        isrc_a_entry = next(t for t in deduped if t["isrc"] == "USAT12345678")
        self.assertEqual(isrc_a_entry["popularity"], 80)

    def test_dedups_by_apple_music_id(self):
        tracks = [
            {"name": "Song A", "artist": "Artist", "apple_music_id": "1234567890", "popularity": 10},
            {"name": "Song A", "artist": "Artist", "apple_music_id": "1234567890", "popularity": 20},
        ]
        deduped = dedupe_tracks_for_selection(tracks)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["popularity"], 20)

    def test_skips_tracks_missing_name_or_artist(self):
        tracks = [
            {"name": "", "artist": "Artist", "isrc": "ABC123"},
            {"name": "Song", "artist": "", "isrc": "DEF456"},
            {"name": "Good", "artist": "Artist", "isrc": "GHI789"},
        ]
        deduped = dedupe_tracks_for_selection(tracks)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["name"], "Good")


# ---------------------------------------------------------------------------
# Integration tests — real API calls
# ---------------------------------------------------------------------------

class TestImportsIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests that call real APIs using a real FastAPI test client.

    Requires Spotify and/or Apple Music credentials in .env.
    """

    async def asyncSetUp(self):
        from app.core.config import settings
        self.settings = settings
        import httpx
        from app.main import app
        from app.clients.apple_music import apple_music_client
        from app.clients.supabase_db import supabase_client
        # Reset singleton HTTP clients so they get fresh event-loop-bound connections
        if apple_music_client._client and not apple_music_client._client.is_closed:
            await apple_music_client._client.aclose()
        apple_music_client._client = None
        if supabase_client._client is not None:
            supabase_client._client = None
        # Manually initialize app.state.http_client (bypasses lifespan in tests)
        self._app_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
        )
        app.state.http_client = self._app_http_client
        self.test_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=60.0,
        )

    async def asyncTearDown(self):
        await self.test_client.aclose()
        # Brief pause to let any background tasks (rate limiter, etc.) complete
        # before the event loop closes
        import asyncio
        await asyncio.sleep(0.1)
        try:
            await self._app_http_client.aclose()
        except Exception:
            pass

    async def _post_import(self, url: str, rank_mode: str = "quick_rank"):
        resp = await self.test_client.post(
            "/imports/playlist",
            json={"url": url, "rank_mode": rank_mode},
        )
        return resp

    # Spotify integration test is in TestSpotifyIntegration below to avoid
    # event-loop interference from the AM+Supabase tests above

    async def test_apple_music_playlist_import_and_source_platform(self):
        """Import an Apple Music playlist and verify session metadata.

        Combined test to avoid hitting the same API endpoint twice in rapid succession.
        """
        if not self.settings.apple_music_configured:
            self.skipTest("Apple Music credentials not configured")

        from app.clients.supabase_db import supabase_client

        # Apple Music "Today's Hits" curated playlist
        resp = await self._post_import(
            "https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb",
            rank_mode="quick_rank",
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("session_id", data)
        self.assertGreater(data["count"], 0)

        # Verify the session was stored with the correct platform metadata
        db_client = await supabase_client.get_client()
        session = await db_client.table("sessions").select(
            "source_platform, collection_metadata"
        ).eq("id", data["session_id"]).single().execute()
        self.assertEqual(session.data["source_platform"], "apple_music")
        self.assertIn("storefront", session.data["collection_metadata"])

class TestURLValidationUnit(unittest.IsolatedAsyncioTestCase):
    """URL validation tests that use a fresh app instance (no Supabase connections)."""

    async def asyncSetUp(self):
        import httpx
        from app.main import app
        from app.clients.apple_music import apple_music_client
        from app.clients.supabase_db import supabase_client
        if apple_music_client._client and not apple_music_client._client.is_closed:
            await apple_music_client._client.aclose()
        apple_music_client._client = None
        supabase_client._client = None
        self._app_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), follow_redirects=True
        )
        app.state.http_client = self._app_http_client
        self.test_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=10.0,
        )

    async def asyncTearDown(self):
        await self.test_client.aclose()
        import asyncio
        await asyncio.sleep(0.05)
        try:
            await self._app_http_client.aclose()
        except Exception:
            pass

    async def test_apple_music_album_url_raises_400(self):
        """An Apple Music album URL (not playlist) should return 400."""
        resp = await self.test_client.post(
            "/imports/playlist",
            json={"url": "https://music.apple.com/us/album/folklore/1516153497"},
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data["detail"]["code"], "INVALID_APPLE_MUSIC_URL")

    async def test_youtube_url_raises_400(self):
        resp = await self.test_client.post(
            "/imports/playlist",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
