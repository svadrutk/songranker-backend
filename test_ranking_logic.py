
import unittest
from app.core.ranking import RankingManager

class TestRankingLogic(unittest.TestCase):
    def test_bt_to_elo(self):
        # Gamma = 1.0 -> Elo 1500
        self.assertAlmostEqual(RankingManager.bt_to_elo(1.0), 1500.0)
        # Gamma = 10.0 -> Elo 1900
        self.assertAlmostEqual(RankingManager.bt_to_elo(10.0), 1900.0)
        # Gamma = 0.1 -> Elo 1100
        self.assertAlmostEqual(RankingManager.bt_to_elo(0.1), 1100.0)

    def test_compute_bradley_terry_simple(self):
        # A beats B twice. A should be stronger.
        song_ids = ["A", "B"]
        comparisons = [
            {"song_a_id": "A", "song_b_id": "B", "winner_id": "A", "is_tie": False},
            {"song_a_id": "B", "song_b_id": "A", "winner_id": "A", "is_tie": False}
        ]
        
        scores = RankingManager.compute_bradley_terry(song_ids, comparisons, iterations=10)
        
        print(f"\nBT Scores (A >> B): {scores}")
        self.assertGreater(scores["A"], scores["B"])

    def test_compute_bradley_terry_tie(self):
        # A ties B. Strengths should be equal (or close due to initialization).
        song_ids = ["A", "B"]
        comparisons = [
            {"song_a_id": "A", "song_b_id": "B", "winner_id": None, "is_tie": True}
        ]
        
        scores = RankingManager.compute_bradley_terry(song_ids, comparisons, iterations=10)
        print(f"\nBT Scores (Tie): {scores}")
        
        # With Laplace smoothing (0.5 wins each), they should be exactly equal
        self.assertAlmostEqual(scores["A"], scores["B"], places=4)

    def test_convergence_logic(self):
        # Quantity
        # 250 duels / (100 songs * 2.5) = 250 / 250 = 1.0
        self.assertEqual(RankingManager.calculate_progress(250, 100), 1.0)
        # 125 duels / 250 = 0.5
        self.assertEqual(RankingManager.calculate_progress(125, 100), 0.5)
        
        # Stability
        prev = ["A", "B", "C", "D", "E"]
        curr = ["A", "B", "C", "F", "G"] # 3 overlap (A,B,C)
        
        # Top 5 stability
        score = RankingManager.calculate_stability_score(prev, curr, top_n=5)
        self.assertEqual(score, 3/5) # 0.6

if __name__ == "__main__":
    unittest.main()
