import math
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

class RankingManager:
    """
    Implements the Bradley-Terry model with MM algorithm and Elo re-calibration.
    """
    
    @staticmethod
    def bt_to_elo(gamma: float) -> float:
        """
        Convert Bradley-Terry strength parameter (gamma) to Elo rating.
        R = 400 * log10(gamma) + 1500
        """
        if gamma <= 0:
            return 1000.0  # Fallback for invalid gamma
        return 400.0 * math.log10(gamma) + 1500.0

    @staticmethod
    def compute_bradley_terry(
        song_ids: List[str],
        comparisons: List[Dict],
        iterations: int = 100,
        tolerance: float = 1e-6
    ) -> Dict[str, float]:
        """
        Iterative MM algorithm to solve for song strengths (p).
        
        Args:
            song_ids: List of unique song IDs involved.
            comparisons: List of comparison dicts {winner_id, loser_id} or {song_a_id, song_b_id, winner_id}.
            iterations: Max number of iterations.
            tolerance: Convergence threshold.
            
        Returns:
            Dict mapping song_id -> bt_strength (gamma).
        """
        n = len(song_ids)
        if n == 0:
            return {}
        
        # Initialize strengths (p) uniformly
        p = {sid: 1.0 for sid in song_ids}
        
        # Build Win Matrix (W) and Comparison Matrix (N)
        # N[i][j] = number of times i played j
        # W[i] = number of times i beat anyone
        
        # We use a dictionary for sparse matrix representation
        # N[(id_i, id_j)] = count
        N: Dict[Tuple[str, str], int] = {}
        W: Dict[str, float] = {sid: 0.0 for sid in song_ids}
        
        # Process comparisons
        for comp in comparisons:
            s_a = str(comp.get("song_a_id", ""))
            s_b = str(comp.get("song_b_id", ""))
            winner = str(comp.get("winner_id", "")) if comp.get("winner_id") else None
            is_tie = bool(comp.get("is_tie", False))
            
            if not s_a or not s_b or s_a not in p or s_b not in p:
                continue
            
            # Use sorted tuple as key for undirected pair
            ids = sorted([s_a, s_b])
            pair = (ids[0], ids[1])
            N[pair] = N.get(pair, 0) + 1
            
            if is_tie:
                W[s_a] += 0.5
                W[s_b] += 0.5
            elif winner == s_a:
                W[s_a] += 1.0
            elif winner == s_b:
                W[s_b] += 1.0
        
        # Laplace smoothing: Add 0.5 virtual wins to every song
        for sid in song_ids:
            W[sid] += 0.5
            
        # MM Iteration
        actual_iterations = 0
        for _ in range(iterations):
            actual_iterations += 1
            sums = {sid: 0.0 for sid in song_ids}

            for (id1, id2), count in N.items():
                denom = p[id1] + p[id2]
                if denom > 0:
                    val = count / denom
                    sums[id1] += val
                    sums[id2] += val

            max_diff = 0.0
            new_p = {}
            for sid in song_ids:
                # Update rule: p_i = W_i / sum(N_ij / (p_i + p_j))
                new_p[sid] = W[sid] / sums[sid] if sums[sid] > 0 else p[sid]
                max_diff = max(max_diff, abs(new_p[sid] - p[sid]))

            p = new_p

            # Normalize to keep values stable (geometric mean = 1)
            log_sum = sum(math.log(max(1e-10, x)) for x in p.values())
            gm = math.exp(log_sum / n)
            p = {k: v / gm for k, v in p.items()}

            if max_diff < tolerance:
                break

        # Log actual iterations for monitoring
        import logging
        logging.info(f"Bradley-Terry converged in {actual_iterations} iterations (max: {iterations}, tolerance: {tolerance})")

        return p

    @staticmethod
    def calculate_progress(total_duels: int, total_songs: int) -> float:
        """
        Quantity Score: Progress based on total_duels / (songs.length * 2.5).
        Capped at 1.0 (100%).
        """
        if total_songs == 0:
            return 1.0
        
        target = total_songs * 2.5
        progress = total_duels / target
        return min(1.0, progress)

    @staticmethod
    def calculate_stability_score(
        prev_ranking: List[str], 
        curr_ranking: List[str], 
        top_n: int = 10
    ) -> float:
        """
        Quality Score: Stability of the Top N list using weighted Rank Correlation.
        Considers both membership and the specific order of the top tracks.
        """
        if not prev_ranking or not curr_ranking:
            return 0.0
            
        p_top = prev_ranking[:top_n]
        c_top = curr_ranking[:top_n]
        
        if not p_top:
            return 0.0

        # 1. Membership Score (Jaccard-ish)
        intersection = set(p_top).intersection(set(c_top))
        membership_score = len(intersection) / top_n

        # 2. Position Score (How many stayed in the exact same spot)
        # We give more weight to higher positions (1st place is more important than 10th)
        position_score = 0.0
        total_weight = 0.0
        for i in range(min(len(p_top), len(c_top))):
            weight = (top_n - i) / top_n
            total_weight += weight
            if p_top[i] == c_top[i]:
                position_score += weight
        
        normalized_position_score = position_score / total_weight if total_weight > 0 else 0.0

        # Final stability is a mix: 40% membership, 60% order
        return (membership_score * 0.4) + (normalized_position_score * 0.6)

    @staticmethod
    def calculate_final_convergence(
        quantity_score: float, 
        stability_score: float,
        weight_quantity: float = 0.5,
        weight_stability: float = 0.5
    ) -> int:
        """
        Weighted average of Quantity and Quality.
        Returns integer 0-100.
        """
        raw_score = (quantity_score * weight_quantity) + (stability_score * weight_stability)
        return int(min(100.0, raw_score * 100))
