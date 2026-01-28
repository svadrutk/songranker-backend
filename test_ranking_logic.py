
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
        # Membership: 3/5 = 0.6
        # Position: Weights (5+4+3+2+1)/5 = 3.0 total. Matches: 5/5, 4/5, 3/5 = 12/5 = 2.4. 2.4/3.0 = 0.8
        # Final: 0.6 * 0.4 + 0.8 * 0.6 = 0.24 + 0.48 = 0.72
        self.assertAlmostEqual(score, 0.72)

    def test_weighted_bradley_terry(self):
        """
        Verify that decision time affects the weight of the win.
        Fast Win (<3s) should yield higher strength than Normal Win.
        Slow Win (>10s) should yield lower strength than Normal Win.
        """
        song_ids = ["A", "B"]
        
        # Helper to get ratio A/B
        def get_ratio(time_ms):
            comps = [{
                "song_a_id": "A", "song_b_id": "B", 
                "winner_id": "A", "is_tie": False,
                "decision_time_ms": time_ms
            }]
            scores = RankingManager.compute_bradley_terry(song_ids, comps, iterations=100)
            return scores["A"] / scores["B"]

        ratio_fast = get_ratio(2000)   # Weight 1.5
        ratio_normal = get_ratio(5000) # Weight 1.0
        ratio_slow = get_ratio(12000)  # Weight 0.5
        
        print(f"\nWeighted Ratios (A/B): Fast={ratio_fast:.2f}, Normal={ratio_normal:.2f}, Slow={ratio_slow:.2f}")
        
        self.assertGreater(ratio_fast, ratio_normal, "Fast win should be stronger than normal")
        self.assertGreater(ratio_normal, ratio_slow, "Normal win should be stronger than slow")

if __name__ == "__main__":
    unittest.main()
