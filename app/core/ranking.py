import math
import logging
from typing import List, Dict, Optional
import numpy as np
import choix

logger = logging.getLogger(__name__)

# Constants for Elo conversion
# choix returns log-strengths (θ), Elo uses log10
# Elo = 400 * log10(e^θ) + 1500 = 400 * θ / ln(10) + 1500
LOG10_E = math.log10(math.e)  # ≈ 0.4343
ELO_SCALE = 400.0 * LOG10_E   # ≈ 173.72
ELO_BASE = 1500.0

# Regularization parameter for choix (prevents divergence with undefeated items)
DEFAULT_ALPHA = 0.01


class RankingManager:
    """
    Implements the Bradley-Terry model using the choix library.
    
    Uses Iterative Luce Spectral Ranking (I-LSR) which is numerically stable
    and handles disconnected comparison graphs via regularization.
    
    Key changes from previous implementation:
    - Uses choix.ilsr_pairwise instead of custom MM algorithm
    - Returns log-strengths (θ) instead of raw probabilities
    - Regularization prevents divergence with undefeated songs
    - Decision time weighting via comparison duplication
    """
    
    @staticmethod
    def theta_to_elo(theta: float) -> float:
        """
        Convert choix log-strength parameter (θ) to Elo rating.
        
        Bradley-Terry: P(i > j) = e^θi / (e^θi + e^θj)
        Elo: P(i > j) = 1 / (1 + 10^((Rj - Ri)/400))
        
        These are equivalent when R = 400 * log10(e^θ) + 1500
                                     = 400 * θ / ln(10) + 1500
        """
        return ELO_SCALE * theta + ELO_BASE
    
    @staticmethod
    def bt_to_elo(gamma: float) -> float:
        """
        Convert Bradley-Terry strength parameter (gamma) to Elo rating.
        R = 400 * log10(gamma) + 1500
        
        DEPRECATED: Use theta_to_elo() for choix log-strengths.
        Kept for backward compatibility with stored bt_strength values.
        """
        if gamma <= 0:
            return 1000.0  # Fallback for invalid gamma
        return 400.0 * math.log10(gamma) + ELO_BASE

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
        tolerance: float = 1e-8,
        initial_p: Optional[Dict[str, float]] = None,
        alpha: float = DEFAULT_ALPHA
    ) -> Dict[str, float]:
        """
        Compute Bradley-Terry strengths using choix's I-LSR algorithm.
        
        Returns log-strengths (θ) for each song. These can be converted to:
        - Elo ratings via theta_to_elo(θ)
        - Win probabilities via P(i > j) = 1 / (1 + e^(θj - θi))
        
        Args:
            song_ids: List of song IDs to rank
            comparisons: List of comparison dicts with song_a_id, song_b_id, winner_id, is_tie, decision_time_ms
            iterations: Max iterations for I-LSR algorithm
            tolerance: Convergence tolerance
            initial_p: Ignored (kept for API compatibility, choix doesn't use warm start the same way)
            alpha: Regularization parameter (default 0.01). Higher values = more regularization.
                   Set > 0 to handle disconnected graphs (e.g., undefeated songs).
        
        Returns:
            Dict mapping song_id to log-strength (θ)
        """
        n = len(song_ids)
        if n == 0:
            return {}
        
        if n == 1:
            # Single song has θ = 0 (average strength)
            return {song_ids[0]: 0.0}
        
        # Map song IDs to indices 0..n-1
        id_to_idx = {sid: i for i, sid in enumerate(song_ids)}
        
        # Convert comparisons to choix format: [[winner_idx, loser_idx], ...]
        # Handle weighted comparisons by duplicating (approximate method)
        data: List[List[int]] = []
        
        for comp in comparisons:
            s_a = str(comp.get("song_a_id", ""))
            s_b = str(comp.get("song_b_id", ""))
            
            if s_a not in id_to_idx or s_b not in id_to_idx:
                continue
                
            idx_a, idx_b = id_to_idx[s_a], id_to_idx[s_b]
            
            winner_id = str(comp.get("winner_id") or "")
            is_tie = comp.get("is_tie", False)
            weight = RankingManager.get_comparison_weight(comp.get("decision_time_ms"))
            
            # Determine repetitions based on weight (1.5 -> 3 reps, 1.0 -> 2 reps, 0.5 -> 1 rep)
            # This approximates weighting by duplicating comparisons
            reps = max(1, round(weight * 2))
            
            if is_tie:
                # Ties: add both directions (each side wins once)
                for _ in range(reps):
                    data.append([idx_a, idx_b])
                    data.append([idx_b, idx_a])
            elif winner_id == s_a:
                for _ in range(reps):
                    data.append([idx_a, idx_b])
            elif winner_id == s_b:
                for _ in range(reps):
                    data.append([idx_b, idx_a])
            # Skip if no winner and not a tie (double loss - treat as no data)
        
        if not data:
            # No valid comparisons: return all zeros (equal strength)
            logger.warning(f"No valid comparisons found for {n} songs")
            return {sid: 0.0 for sid in song_ids}
        
        # Use choix's I-LSR algorithm with regularization
        try:
            params = choix.ilsr_pairwise(
                n_items=n,
                data=data,
                alpha=alpha,
                max_iter=iterations,
                tol=tolerance
            )
            
            logger.info(f"I-LSR completed: {len(data)} comparisons, θ range [{params.min():.3f}, {params.max():.3f}]")
            
        except Exception as e:
            logger.error(f"choix.ilsr_pairwise failed: {e}")
            # Fallback: return zeros
            return {sid: 0.0 for sid in song_ids}
        
        # Map back to song IDs
        return {sid: float(params[idx]) for sid, idx in id_to_idx.items()}

    @staticmethod
    def calculate_coverage(comparisons: List[Dict], n_songs: int, song_ids: Optional[List[str]] = None) -> float:
        """
        Calculate coverage based on how well each song has been compared.
        
        Two components:
        1. What fraction of songs have been compared at least 3 times (with actual data)?
        2. How many meaningful comparisons relative to a reasonable target?
        
        IDC responses (no winner, not a tie) are discounted since they provide no ranking data.
        
        Returns:
            Float between 0 and 1
        """
        if n_songs <= 1:
            return 1.0
        
        if not comparisons:
            return 0.0
        
        # Count MEANINGFUL comparisons per song (exclude IDC)
        # IDC = winner_id is None/empty AND is_tie is False
        comp_per_song: Dict[str, int] = {}
        meaningful_count = 0
        
        for comp in comparisons:
            a = str(comp.get("song_a_id", ""))
            b = str(comp.get("song_b_id", ""))
            winner_id = comp.get("winner_id")
            is_tie = comp.get("is_tie", False)
            
            # Check if this is a meaningful comparison (has winner or is tie)
            is_meaningful = bool(winner_id) or is_tie
            
            if is_meaningful:
                meaningful_count += 1
                if a:
                    comp_per_song[a] = comp_per_song.get(a, 0) + 1
                if b:
                    comp_per_song[b] = comp_per_song.get(b, 0) + 1
            # IDC responses don't count toward per-song coverage
        
        # Component 1: Fraction of songs with >= 3 meaningful comparisons
        min_comparisons = 3
        songs_with_enough = sum(1 for c in comp_per_song.values() if c >= min_comparisons)
        song_coverage = songs_with_enough / n_songs if n_songs > 0 else 0
        
        # Component 2: Meaningful comparisons relative to target
        # Target: n_songs * 1.5 comparisons
        target_comparisons = n_songs * 1.5
        quantity = min(1.0, meaningful_count / target_comparisons) if target_comparisons > 0 else 0
        
        # Combined: need BOTH good per-song coverage AND enough total comparisons
        combined = math.sqrt(song_coverage * quantity)
        
        return combined
    
    @staticmethod
    def calculate_separation(
        bt_params: Dict[str, float],
        comparisons: Optional[List[Dict]] = None
    ) -> float:
        """
        Calculate how well-separated and confident the rankings are.
        
        Two components:
        1. Are θ values well-spread? (can distinguish songs)
        2. Do we have enough data per song to trust the rankings?
        
        Returns:
            Float between 0 and 1 (1 = well separated and confident, 0 = uncertain)
        """
        if not bt_params or len(bt_params) <= 1:
            return 1.0
        
        values = np.array(list(bt_params.values()))
        n = len(values)
        
        param_range = values.max() - values.min()
        if param_range < 0.01:
            # All songs have nearly identical strength - not separated
            return 0.0
        
        # Component 1: Range score (are songs distinguishable?)
        # θ range of 4 is excellent separation
        range_score = min(1.0, param_range / 4.0)
        
        # Component 2: Uniformity (are songs evenly distributed?)
        sorted_vals = np.sort(values)
        gaps = np.diff(sorted_vals)
        expected_gap = param_range / (n - 1) if n > 1 else 1.0
        
        if expected_gap > 0.001:
            gap_variance = np.var(gaps) / (expected_gap ** 2)
            uniformity_score = 1.0 / (1.0 + gap_variance)
        else:
            uniformity_score = 0.0
        
        # Component 3: Confidence (do songs have enough meaningful comparisons?)
        # Only if comparisons provided. IDC responses are discounted.
        confidence_score = 1.0
        if comparisons:
            comp_per_song: Dict[str, int] = {}
            for comp in comparisons:
                # Only count meaningful comparisons (has winner or is tie)
                winner_id = comp.get("winner_id")
                is_tie = comp.get("is_tie", False)
                is_meaningful = bool(winner_id) or is_tie
                
                if not is_meaningful:
                    continue  # Skip IDC responses
                
                a = str(comp.get("song_a_id", ""))
                b = str(comp.get("song_b_id", ""))
                if a in bt_params:
                    comp_per_song[a] = comp_per_song.get(a, 0) + 1
                if b in bt_params:
                    comp_per_song[b] = comp_per_song.get(b, 0) + 1
            
            # Penalize if songs have < 3 meaningful comparisons
            # Calculate average "confidence" per song (capped at 1.0 when >= 3 comparisons)
            confidences = [min(1.0, comp_per_song.get(sid, 0) / 3.0) for sid in bt_params.keys()]
            confidence_score = np.mean(confidences) if confidences else 0.0
        
        # Combined: all three components matter
        # - Range: 30% (can we distinguish songs?)
        # - Uniformity: 20% (are rankings evenly spread?)
        # - Confidence: 50% (do we trust the data?)
        return range_score * 0.3 + uniformity_score * 0.2 + confidence_score * 0.5
    
    @staticmethod
    def calculate_top10_stability(
        comparisons: List[Dict],
        bt_params: Dict[str, float],
        lookback: int = 3
    ) -> float:
        """
        Check if the top 10 ranking has been stable over recent comparisons.
        
        Compares current ranking with ranking from `lookback` comparisons ago.
        Returns a stability score (0.0 to 1.0).
        
        Args:
            comparisons: All comparisons in chronological order
            bt_params: Current BT parameters (from all comparisons)
            lookback: How many comparisons to look back (default 3 for responsiveness)
        
        Returns:
            Float between 0 and 1 (1 = perfectly stable, 0 = unstable)
        """
        if len(comparisons) < lookback + 10:
            # Not enough data to assess stability
            return 0.0
        
        # Get current top 10 and top 5
        current_ranking = sorted(bt_params.items(), key=lambda x: -x[1])
        current_top10 = [sid for sid, _ in current_ranking[:10]]
        current_top5 = current_top10[:5]
        
        # Compute ranking from `lookback` comparisons ago
        song_ids = list(bt_params.keys())
        earlier_comparisons = comparisons[:-lookback]
        
        try:
            earlier_params = RankingManager.compute_bradley_terry(song_ids, earlier_comparisons)
            earlier_ranking = sorted(earlier_params.items(), key=lambda x: -x[1])
            earlier_top10 = [sid for sid, _ in earlier_ranking[:10]]
            earlier_top5 = earlier_top10[:5]
        except Exception:
            return 0.0
        
        # Compare rankings with nuance
        same_top10_order = current_top10 == earlier_top10
        same_top10_membership = set(current_top10) == set(earlier_top10)
        same_top5_order = current_top5 == earlier_top5
        same_top5_membership = set(current_top5) == set(earlier_top5)
        
        if same_top10_order:
            return 1.0  # Perfect stability
        elif same_top5_order and same_top10_membership:
            return 0.95  # Top 5 exact, only bottom 5 shuffled
        elif same_top5_membership and same_top10_membership:
            return 0.85  # Same songs, minor reordering
        elif same_top10_membership:
            return 0.75  # Same top 10 songs, different order
        elif same_top5_membership:
            return 0.6  # Top 5 stable, some churn in 6-10
        else:
            # Count overlap
            overlap = len(set(current_top10) & set(earlier_top10))
            return overlap / 10.0 * 0.5  # Partial credit for overlap
    
    @staticmethod
    def calculate_convergence_v2(
        comparisons: List[Dict],
        n_songs: int,
        bt_params: Dict[str, float]
    ) -> int:
        """
        Improved convergence score based on:
        - 40% Coverage: Do all songs have enough comparisons?
        - 40% Separation: Are rankings well-differentiated AND confident?
        - 20% Stability: Has the top 10 ranking been consistent?
        
        Key features:
        - Stability bonus when top 10 hasn't changed
        - Hard cap at 65% if any song has < 2 comparisons
        - Hard cap at 85% if any song has < 3 comparisons
        
        Args:
            comparisons: List of comparison dicts
            n_songs: Number of songs in the session
            bt_params: Dict of song_id -> θ (log-strength) from Bradley-Terry
        
        Returns:
            Integer 0-100 representing convergence percentage
        """
        if n_songs <= 1:
            return 100
        
        if not comparisons:
            return 0
        
        # Count MEANINGFUL comparisons per song (exclude IDC)
        # IDC = winner_id is None/empty AND is_tie is False
        comp_per_song: Dict[str, int] = {}
        for comp in comparisons:
            winner_id = comp.get("winner_id")
            is_tie = comp.get("is_tie", False)
            is_meaningful = bool(winner_id) or is_tie
            
            if not is_meaningful:
                continue  # Skip IDC responses for min_comps calculation
            
            a = str(comp.get("song_a_id", ""))
            b = str(comp.get("song_b_id", ""))
            if a in bt_params:
                comp_per_song[a] = comp_per_song.get(a, 0) + 1
            if b in bt_params:
                comp_per_song[b] = comp_per_song.get(b, 0) + 1
        
        # Ensure all songs are counted (some may have 0 meaningful comparisons)
        for sid in bt_params.keys():
            if sid not in comp_per_song:
                comp_per_song[sid] = 0
        
        # Find minimum meaningful comparisons for any song
        min_comps = min(comp_per_song.values()) if comp_per_song else 0
        
        # 1. Coverage score (40% weight)
        coverage = RankingManager.calculate_coverage(comparisons, n_songs)
        coverage_score = min(1.0, coverage)
        
        # 2. Separation score (40% weight)
        separation_score = RankingManager.calculate_separation(bt_params, comparisons)
        
        # 3. Stability score (20% weight) - NEW
        stability_score = RankingManager.calculate_top10_stability(comparisons, bt_params, lookback=5)
        
        # Combined score with stability bonus
        raw_score = coverage_score * 0.4 + separation_score * 0.4 + stability_score * 0.2
        
        # Apply curve (gentler curve for faster convergence)
        curved_score = math.pow(raw_score, 0.7) if raw_score < 1.0 else 1.0
        convergence = int(min(100, curved_score * 100))
        
        # Hard caps based on minimum comparisons per song
        # These ensure we don't claim high convergence when data is insufficient
        if min_comps < 2:
            convergence = min(convergence, 65)  # Very uncertain
        elif min_comps < 3:
            convergence = min(convergence, 85)  # Somewhat uncertain
        
        # Stability override: if top 10 is stable, allow higher convergence
        # even if some songs are under-compared (they're clearly not in top 10)
        if stability_score >= 0.95 and min_comps >= 2:
            convergence = max(convergence, 92)  # Very stable = at least 92%
        elif stability_score >= 0.85 and min_comps >= 2:
            convergence = max(convergence, 90)  # Stable = at least 90%
        elif stability_score >= 0.75 and min_comps >= 2:
            convergence = max(convergence, 88)  # Mostly stable = at least 88%
        
        return convergence

    # ==================== Legacy methods (kept for compatibility) ====================
    
    @staticmethod
    def calculate_progress(total_duels: int, total_songs: int) -> float:
        """
        LEGACY: Quantity Score based on total_duels / (songs * 2.5).
        
        Kept for backward compatibility. Use calculate_convergence_v2 instead.
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
        LEGACY: Stability of Top N using weighted rank correlation.
        
        Kept for backward compatibility. Use calculate_convergence_v2 instead.
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
        position_score = 0.0
        total_weight = 0.0
        
        limit = min(len(p_top), len(c_top))
        for i in range(limit):
            weight = (top_n - i) / top_n
            total_weight += weight
            if p_top[i] == c_top[i]:
                position_score += weight
        
        normalized_position_score = position_score / total_weight if total_weight > 0 else 0.0

        return (membership_score * 0.4) + (normalized_position_score * 0.6)

    @staticmethod
    def calculate_final_convergence(
        quantity_score: float, 
        stability_score: float,
        weight_quantity: float = 0.5,
        weight_stability: float = 0.5
    ) -> int:
        """
        LEGACY: Weighted average of Quantity and Stability.
        
        Kept for backward compatibility. Use calculate_convergence_v2 instead.
        """
        raw_score = (quantity_score * weight_quantity) + (stability_score * weight_stability)
        return int(min(100.0, raw_score * 100))
