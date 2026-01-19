# Song Ranker - Master Development Plan

## 📊 Executive Summary
Song Ranker is an interactive web application for ranking songs through pairwise comparisons. It uses a hybrid mathematical approach: **Elo** in the frontend for immediate interactivity and pairing, and the **Bradley-Terry Model** in the backend as the statistical source of truth for the final ranking.

## 🏗️ Technical Architecture

### Frontend (Interactivity & Speed)
- **Framework**: Next.js 16 (App Router), TypeScript, Tailwind CSS 4.
- **Deduplication**: Regex-based normalization and fuzzy matching (Levenshtein) with a "Confidence Score" to catch near-duplicates before session start.
- **Ranking Engine**: Local **Elo Rating System** (starting at 1500).
- **Pairing Strategy**: Selection of pairs with similar Elo ratings to maximize information gain per duel.

### Backend (Accuracy & Persistence)
- **Framework**: FastAPI (Python), Supabase (PostgreSQL).
- **Deep Deduplication**: Asynchronous background task using `RapidFuzz` for intensive matching across the session's song set.
- **Ranking Engine**: **Bradley-Terry MM (Minorization-Maximization) Algorithm**.
- **Model Sync**: Computes updated strength parameters ($p_i$) every 10–15 duels and returns them to the frontend to calibrate the "Official Ranking."

---

## 📅 Phased Development Roadmap

### Phase 1: Deduplication & Review (Frontend)
- **Normalization**: Strip "Instrumental", "Remastered", "Live", etc.
- **Fuzzy Matching**: Identify potential duplicates with uncertainty scores.
  - **High Confidence (>90)**: Auto-merge.
  - **Medium Confidence (70-90)**: Show in "Review & Merge" screen.
- **UI**: Implement the "Review & Merge" modal before session initialization.

### Phase 2: Session & Data Persistence (Backend)
- **Supabase Schema**: Implement `sessions`, `session_songs`, `comparisons`, and `songs` tables.
- **Convergence Tracking**: Add `convergence_score` and `last_active_at` to sessions to manage data lifecycle.
- **API**: 
  - `POST /sessions`: Initialize session with deduplicated song list.
  - `BackgroundTasks`: Trigger deep fuzzy matching and update session "aliases."

### Phase 3: The Ranking Loop & Elo (Frontend)
- **Logic**: Implement `lib/elo.ts` for real-time rating updates.
- **UI**: Transform `RankingWidget` into an active duel interface with "Song A", "Song B", and "Tie" options.
- **Feedback**: Immediate UI updates after each selection.

### Phase 4: Bradley-Terry & Model Sync (Backend)
- **Algorithm**: Implement Bradley-Terry MM in the backend.
- **Trigger**: Run calculation every 10–15 duels.
- **Sync**: Return BT strengths to frontend; recalibrate local Elo ratings to match BT ordering.

### Phase 5: Results & Polish
- **View**: Official leaderboard display based on BT scores.
- **Stability**: Logic to detect when ranking has converged.
- **UX**: Smooth transitions, progress tracking, and mobile optimization.

---

## 🗄️ Database Schema (Supabase/PostgreSQL)

### `songs`
- `id`: UUID (PK)
- `name`: Text
- `artist`: Text
- `album_id`: UUID (FK)
- `normalized_name`: Text (for matching)

### `sessions`
- `id`: UUID (PK)
- `user_id`: UUID (FK)
- `status`: Enum ('active', 'completed')
- `convergence_score`: Float (0.0 to 1.0)
- `last_active_at`: Timestamp
- `created_at`: Timestamp

### `session_songs`
- `session_id`: UUID (FK)
- `song_id`: UUID (FK)
- `local_elo`: Float
- `bt_strength`: Float

### `comparisons`
- `id`: UUID (PK)
- `session_id`: UUID (FK)
- `song_a_id`: UUID (FK)
- `song_b_id`: UUID (FK)
- `winner_id`: UUID (FK, Nullable for Tie)
- `is_tie`: Boolean
- `created_at`: Timestamp

---

## 🎯 Success Criteria
1. **No Duplicates**: The user never sees the same song twice or "near-duplicates" in a single session.
2. **Snappy UX**: Duels feel instant; mathematical heavy lifting happens in the background.
3. **Statistical Integrity**: The final ranking reflects the Bradley-Terry model's probabilistic strengths.
