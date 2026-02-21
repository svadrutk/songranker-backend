"""
Tests for AppleMusicClient.

Mix of:
 - Pure unit tests (no network) for pure-logic helpers
 - Real API integration tests against the live Apple Music API
   (uses the credentials in .env — requires APPLE_MUSIC_* vars to be set)
"""

import unittest
import asyncio

from app.clients.apple_music import AppleMusicClient, apple_music_client
from app.api.v1.imports import extract_apple_music_playlist_info
from app.core.utils import is_apple_music_id, is_spotify_id


# ---------------------------------------------------------------------------
# Unit tests — no network
# ---------------------------------------------------------------------------

class TestReleaseTypeClassification(unittest.TestCase):
    def _type(self, **attrs):
        return AppleMusicClient._get_release_type(attrs)

    def test_compilation_wins_over_track_count(self):
        self.assertEqual(self._type(isCompilation=True, trackCount=12), "Compilation")

    def test_single_by_is_single_flag(self):
        self.assertEqual(self._type(isSingle=True, trackCount=1), "Single")

    def test_single_by_track_count_1(self):
        self.assertEqual(self._type(isSingle=False, trackCount=1), "Single")

    def test_single_by_track_count_3(self):
        self.assertEqual(self._type(isSingle=False, trackCount=3), "Single")

    def test_ep_by_track_count_4(self):
        self.assertEqual(self._type(isSingle=False, trackCount=4), "EP")

    def test_ep_by_track_count_6(self):
        self.assertEqual(self._type(isSingle=False, trackCount=6), "EP")

    def test_ep_by_name(self):
        self.assertEqual(self._type(isSingle=False, trackCount=3, name="Something - EP"), "EP")

    def test_album_by_track_count_7(self):
        self.assertEqual(self._type(isSingle=False, trackCount=7), "Album")

    def test_album_by_track_count_large(self):
        self.assertEqual(self._type(isSingle=False, trackCount=20), "Album")


class TestArtworkResolution(unittest.TestCase):
    TEMPLATE = "https://is1-ssl.mzstatic.com/image/thumb/Music/{w}x{h}bb.jpg"

    def test_resolves_template_to_500(self):
        result = AppleMusicClient._resolve_artwork({"url": self.TEMPLATE}, size=500)
        self.assertEqual(result, "https://is1-ssl.mzstatic.com/image/thumb/Music/500x500bb.jpg")

    def test_resolves_template_to_300(self):
        result = AppleMusicClient._resolve_artwork({"url": self.TEMPLATE}, size=300)
        self.assertIn("300x300", result)

    def test_handles_missing_url(self):
        self.assertIsNone(AppleMusicClient._resolve_artwork({}))

    def test_handles_url_without_template_vars(self):
        url = "https://is1-ssl.mzstatic.com/plain/image.jpg"
        result = AppleMusicClient._resolve_artwork({"url": url}, size=500)
        # No template vars — URL returned unchanged
        self.assertEqual(result, url)


class TestAppleMusicPlaylistURLParsing(unittest.TestCase):
    def test_standard_url(self):
        url = "https://music.apple.com/us/playlist/my-playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde"
        playlist_id, storefront = extract_apple_music_playlist_info(url)
        self.assertEqual(playlist_id, "pl.cb4d1c09a2df4230a78d0395fe1f8fde")
        self.assertEqual(storefront, "us")

    def test_url_without_slug(self):
        url = "https://music.apple.com/gb/playlist/pl.cb4d1c09a2df4230a78d0395fe1f8fde"
        playlist_id, storefront = extract_apple_music_playlist_info(url)
        self.assertEqual(playlist_id, "pl.cb4d1c09a2df4230a78d0395fe1f8fde")
        self.assertEqual(storefront, "gb")

    def test_url_with_query_params(self):
        url = "https://music.apple.com/us/playlist/my-playlist/pl.f4d106fed2bd41149aaacabb233eb5eb?app=music"
        playlist_id, storefront = extract_apple_music_playlist_info(url)
        self.assertEqual(playlist_id, "pl.f4d106fed2bd41149aaacabb233eb5eb")
        self.assertEqual(storefront, "us")

    def test_invalid_url_returns_none(self):
        playlist_id, storefront = extract_apple_music_playlist_info("https://open.spotify.com/playlist/abc")
        self.assertIsNone(playlist_id)
        self.assertEqual(storefront, "us")


class TestIDDetection(unittest.TestCase):
    def test_apple_music_id_numeric(self):
        self.assertTrue(is_apple_music_id("1440935467"))
        self.assertTrue(is_apple_music_id("123"))

    def test_apple_music_id_rejects_non_numeric(self):
        self.assertFalse(is_apple_music_id("1440935abc"))
        self.assertFalse(is_apple_music_id("pl.abc123"))

    def test_spotify_id_valid(self):
        self.assertTrue(is_spotify_id("6rqhFgbbKwnb9MLmUQDhG6"))
        self.assertTrue(is_spotify_id("1Ib1CSSHuBDYNPoH2GJbkZ"))

    def test_spotify_id_rejects_all_digits(self):
        # 22-digit pure numeric string: used to be accepted, now rejected (AM ID)
        self.assertFalse(is_spotify_id("1234567890123456789012"))

    def test_spotify_id_rejects_uuid(self):
        self.assertFalse(is_spotify_id("550e8400-e29b-41d4-a716-446655440000"))

    def test_spotify_id_rejects_short(self):
        self.assertFalse(is_spotify_id("shortid"))


# ---------------------------------------------------------------------------
# Integration tests — hit real Apple Music API
# ---------------------------------------------------------------------------

class TestAppleMusicClientIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests against the live Apple Music API.

    These will be skipped automatically if credentials are not configured.
    Each test gets a fresh AppleMusicClient to avoid event loop conflicts.
    """

    def setUp(self):
        from app.core.config import settings
        if not settings.apple_music_configured:
            self.skipTest("Apple Music credentials not configured")

    async def asyncSetUp(self):
        # Fresh client per test — avoids event loop closed errors from shared singleton
        self.client = AppleMusicClient()

    async def asyncTearDown(self):
        if self.client._client and not self.client._client.is_closed:
            await self.client._client.aclose()

    async def test_jwt_generation(self):
        token = self.client._generate_jwt()
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 100)
        self.assertEqual(len(token.split(".")), 3)

    async def test_jwt_cached_on_reuse(self):
        token1 = self.client._generate_jwt()
        token2 = self.client._generate_jwt()
        self.assertEqual(token1, token2)

    async def test_search_artist_albums_returns_results(self):
        results = await self.client.search_artist_albums("Taylor Swift")
        self.assertGreater(len(results), 5)
        first = results[0]
        self.assertIn("id", first)
        self.assertIn("title", first)
        self.assertIn("artist", first)
        self.assertIn("type", first)
        self.assertIn("cover_art", first)
        self.assertEqual(first["source"], "apple_music")

    async def test_search_returns_albums_not_singles_only(self):
        results = await self.client.search_artist_albums("Kendrick Lamar")
        types = {r["type"] for r in results}
        self.assertIn("Album", types)

    async def test_search_artwork_url_has_no_template(self):
        results = await self.client.search_artist_albums("Drake")
        for r in results:
            url = r["cover_art"]["url"]
            if url:
                self.assertNotIn("{w}", url)
                self.assertNotIn("{h}", url)

    async def test_search_artists_only_returns_names(self):
        names = await self.client.search_artists_only("Beyonce")
        self.assertGreater(len(names), 0)
        self.assertTrue(all(isinstance(n, str) for n in names))

    async def test_get_album_tracks_returns_list(self):
        # Reputation by Taylor Swift
        tracks = await self.client.get_album_tracks("1445765846")
        self.assertGreater(len(tracks), 5)
        self.assertTrue(all(isinstance(t, str) for t in tracks))

    async def test_get_playlist_metadata(self):
        meta = await self.client.get_playlist_metadata(
            "pl.f4d106fed2bd41149aaacabb233eb5eb", "us"
        )
        self.assertIsNotNone(meta["name"])
        self.assertIsInstance(meta["name"], str)

    async def test_get_playlist_tracks_returns_tracks_with_isrc(self):
        tracks = await self.client.get_playlist_tracks(
            "pl.f4d106fed2bd41149aaacabb233eb5eb", "us", limit=10
        )
        self.assertGreater(len(tracks), 0)
        first = tracks[0]
        self.assertIn("name", first)
        self.assertIn("artist", first)
        self.assertIn("isrc", first)
        self.assertIn("apple_music_id", first)
        self.assertIsNone(first["spotify_id"])
        tracks_with_isrc = sum(1 for t in tracks if t.get("isrc"))
        self.assertGreater(tracks_with_isrc, len(tracks) * 0.8)

    async def test_get_playlist_tracks_respects_limit(self):
        tracks = await self.client.get_playlist_tracks(
            "pl.f4d106fed2bd41149aaacabb233eb5eb", "us", limit=5
        )
        self.assertLessEqual(len(tracks), 5)

    async def test_private_playlist_raises_after_retries(self):
        import httpx
        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            await self.client.get_playlist_tracks(
                "pl.0000000000000000000000000000fake", "us", limit=5
            )
        self.assertEqual(ctx.exception.response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
