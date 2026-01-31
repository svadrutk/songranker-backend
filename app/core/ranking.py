import math
import logging
from typing import List, Dict, Optional
import numpy as np

logger = logging.getLogger(__name__)

class RankingManager:
    """
    Implements the Bradley-Terry model with MM algorithm and Elo re-calibration.
    Optimized with NumPy and Warm Start.
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
    def get_comparison_weight(decision_time_ms: Optional[int]) -> float:
        """
        Calculate weight based on decision speed.
        < 3s  -> 1.5 (High confidence)
        > 10s -> 0.5 (Low confidence)
        Else  -> 1.0
        """
        if decision_time_ms is None:
            return 1.0
        if decision_time_ms < 3000:
            return 1.5
        if decision_time_ms > 10000:
            return 0.5
        return 1.0

    @staticmethod
    def compute_bradley_terry(
        song_ids: List[str],
        comparisons: List[Dict],
        iterations: int = 100,
        tolerance: float = 1e-4,
        initial_p: Optional[Dict[str, float]] = None
    ) -> Dict[str, float]:
        """
        Iterative MM algorithm to solve for song strengths (p) using NumPy.
        Supports warm start via initial_p.
        Weighted by decision time.
        """
        n = len(song_ids)
        if n == 0:
            return {}
        
        # Map song IDs to indices 0..n-1
        id_to_idx = {sid: i for i, sid in enumerate(song_ids)}
        
        # Initialize strengths (p)
        # Default to 1.0, or use warm start values
        p = np.ones(n, dtype=np.float64)
        if initial_p:
            for sid, val in initial_p.items():
                if sid in id_to_idx:
                    p[id_to_idx[sid]] = max(float(val), 1e-6)

        # Build Win Vector (W) and Pair Data
        W = np.zeros(n, dtype=np.float64)
        
        # Use a dict to aggregate pair counts: (idx_min, idx_max) -> count
        pair_counts = {}
        
        for comp in comparisons:
            s_a = str(comp.get("song_a_id", ""))
            s_b = str(comp.get("song_b_id", ""))
            
            if s_a not in id_to_idx or s_b not in id_to_idx:
                continue
                
            idx_a, idx_b = id_to_idx[s_a], id_to_idx[s_b]
            
            winner_id = str(comp.get("winner_id") or "")
            is_tie = comp.get("is_tie", False)
            weight = RankingManager.get_comparison_weight(comp.get("decision_time_ms"))

            # Update W (Win counts)
            if is_tie:
                W[idx_a] += 0.5 * weight
                W[idx_b] += 0.5 * weight
            elif winner_id == s_a:
                W[idx_a] += 1.0 * weight
            elif winner_id == s_b:
                W[idx_b] += 1.0 * weight
                
            # Update Pair counts (N_ij) with weight
            pair_key = tuple(sorted((idx_a, idx_b)))
            pair_counts[pair_key] = pair_counts.get(pair_key, 0.0) + weight
            
        # Laplace smoothing: Add 0.5 virtual wins to every song
        # Note: Smoothing remains unweighted (base prior)
        W += 0.5
        
        if not pair_counts:
            # Return current p if no comparisons
            return {sid: float(p[i]) for sid, i in id_to_idx.items()}

        # Prepare arrays for vectorized MM
        pairs = np.array(list(pair_counts.keys()), dtype=np.int32)
        counts = np.array(list(pair_counts.values()), dtype=np.float64)
        
        idx_i = pairs[:, 0]
        idx_j = pairs[:, 1]
        
        actual_iterations = 0
        
        # MM Iteration
        for _ in range(iterations):
            actual_iterations += 1
            
            # 1. Compute pairwise sums: p_i + p_j
            # Since idx_i and idx_j are indices into p
            sums = p[idx_i] + p[idx_j]
            
            # 2. Compute ratios: N_ij / (p_i + p_j)
            # Avoid division by zero
            valid_sums = np.maximum(sums, 1e-12)
            ratios = counts / valid_sums
            
            # 3. Accumulate denominator sums
            # denom_sums[k] = sum_{j!=k} N_kj / (p_k + p_j)
            denom = np.zeros(n, dtype=np.float64)
            np.add.at(denom, idx_i, ratios)
            np.add.at(denom, idx_j, ratios)
            
            # 4. Update p
            # p_new[k] = W[k] / denom[k]
            # Handle isolated songs: if denom is 0, keep previous p (don't explode)
            mask = denom > 1e-12
            p_new = p.copy()
            p_new[mask] = W[mask] / denom[mask]
            
            # Check convergence
            max_diff = np.max(np.abs(p_new - p))
            p = p_new
            
            # Geometric Mean Normalization
            # log_sum = sum(log(p))
            # gm = exp(log_sum / n)
            # p = p / gm
            
            # Use safe log
            log_vals = np.log(np.maximum(p, 1e-12))
            log_mean = np.mean(log_vals)
            gm = np.exp(log_mean)
            p = p / gm
            
            if max_diff < tolerance:
                break
                
        logger.info(f"Bradley-Terry converged in {actual_iterations} iterations (max: {iterations}, tolerance: {tolerance})")
        
        return {sid: float(p[i]) for sid, i in id_to_idx.items()}

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
        
        limit = min(len(p_top), len(c_top))
        for i in range(limit):
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
