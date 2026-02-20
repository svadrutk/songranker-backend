import unittest

from app.core.track_selection import dedupe_tracks_for_selection, select_anchor_variance_quick_rank


class TestTrackSelection(unittest.TestCase):
    def test_dedupe_prefers_higher_popularity(self):
        tracks = [
            {"name": "Song", "artist": "A", "isrc": "X", "spotify_id": "id1", "popularity": 10},
            {"name": "Song", "artist": "A", "isrc": "X", "spotify_id": "id2", "popularity": 90},
        ]
        deduped = dedupe_tracks_for_selection(tracks)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["popularity"], 90)

    def test_quick_rank_selects_30_20(self):
        tracks = []
        for i in range(100):
            tracks.append({
                "name": f"Song {i}",
                "artist": "Artist",
                "isrc": f"ISRC{i}",
                "spotify_id": f"id{i}",
                "popularity": i,
            })

        result = select_anchor_variance_quick_rank(tracks, anchors=30, wildcards=20, seed="playlist")
        self.assertEqual(len(result), 50)

        # Top 30 popularity are 99..70
        anchor_isrcs = {f"ISRC{i}" for i in range(70, 100)}
        result_isrcs = {t.get("isrc") for t in result}
        self.assertTrue(anchor_isrcs.issubset(result_isrcs))

        # Exactly 20 should come from outside the top 30 by popularity.
        non_anchor_count = sum(1 for t in result if int(t.get("popularity") or 0) < 70)
        self.assertEqual(non_anchor_count, 20)

    def test_quick_rank_returns_all_when_under_target(self):
        tracks = [
            {"name": f"Song {i}", "artist": "Artist", "isrc": f"ISRC{i}", "spotify_id": f"id{i}", "popularity": i}
            for i in range(12)
        ]
        result = select_anchor_variance_quick_rank(tracks, anchors=30, wildcards=20, seed="playlist")
        self.assertEqual(len(result), 12)


if __name__ == "__main__":
    unittest.main()
