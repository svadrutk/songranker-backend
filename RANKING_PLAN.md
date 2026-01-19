# Ranking System Implementation Plan (Backend)

## 🎯 Goal
Implement a robust statistical ranking system using the Bradley-Terry model, processed asynchronously via Redis, with automated Elo re-calibration and convergence tracking.

## 🏗️ Architecture

### 1. Core Logic (`app/core/ranking.py`)
- **Bradley-Terry MM Algorithm**: Iterative solver for song strengths.
- **Laplace Smoothing**: Add `0.5` virtual wins/losses to handle sparse data and prevent divide-by-zero.
- **Elo Re-calibration**: Map BT strengths back to Elo ($R = 400 \cdot \log_{10}(\gamma) + 1500$) to keep pairing competitive.
- **Convergence/Progress Engine**:
    - **Quantity Score**: Progress based on `total_duels / (songs.length * 2.5)`.
    - **Quality Score**: Stability of the Top 10 list between consecutive runs.
    - **Final Progress**: Weighted average of Quantity and Quality.

### 2. Database Integration (`app/clients/supabase_db.py`)
- `get_session_comparisons(session_id)`: Retrieve all raw duel results.
- `update_session_results(session_id, updates, progress)`: 
    - Bulk update `bt_strength` and `local_elo` in `session_songs`.
    - Update `convergence_score` and `last_active_at` in `sessions`.

### 3. Background Processing (`app/tasks.py`)
- `run_ranking_update(session_id)`:
    1. Fetch duels.
    2. Compute BT strengths and calibrated Elos.
    3. Calculate Top 10 stability (convergence).
    4. Persist results to Supabase.

### 4. API Layer (`app/api/v1/sessions.py`)
- Modify `create_comparison`:
    - Check `total_duels % 5 == 0`.
    - Enqueue `run_ranking_update` if true.
    - Return `sync_queued: boolean` and current `convergence_score`.

## 📈 Success Criteria
- BT Model converges in < 100ms for 100 songs.
- Elo ratings stay centered at 1500.
- Worker correctly processes 5-duel batches without dropping tasks.
