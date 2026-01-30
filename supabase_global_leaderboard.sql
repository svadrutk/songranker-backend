-- ============================================
-- Global Leaderboard Migration
-- ============================================
-- This migration adds support for cross-session global rankings
-- for artists, allowing users to see platform-wide leaderboards.

-- 1. Add global ranking columns to songs table
ALTER TABLE songs 
ADD COLUMN IF NOT EXISTS global_elo FLOAT8 DEFAULT 1500.0,
ADD COLUMN IF NOT EXISTS global_bt_strength FLOAT8 DEFAULT 1.0,
ADD COLUMN IF NOT EXISTS global_votes_count INT4 DEFAULT 0;

-- 2. Create artist_stats table to track global update timestamps
CREATE TABLE IF NOT EXISTS artist_stats (
    artist TEXT PRIMARY KEY,
    last_global_update_at TIMESTAMPTZ DEFAULT NOW(),
    total_comparisons_count BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create indexes for optimal leaderboard query performance
CREATE INDEX IF NOT EXISTS idx_songs_artist_global_elo 
ON songs (artist, global_elo DESC);

-- 4. Create indexes on comparisons table for fast aggregation queries
CREATE INDEX IF NOT EXISTS idx_comparisons_song_a_id 
ON comparisons (song_a_id);

CREATE INDEX IF NOT EXISTS idx_comparisons_song_b_id 
ON comparisons (song_b_id);

-- 5. RPC function to fetch all comparisons for a specific artist
-- This aggregates duels across all sessions where both songs belong to the artist
CREATE OR REPLACE FUNCTION get_artist_comparisons(p_artist TEXT)
RETURNS TABLE (
    song_a_id UUID,
    song_b_id UUID,
    winner_id UUID,
    is_tie BOOLEAN,
    decision_time_ms INTEGER
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.song_a_id,
        c.song_b_id,
        c.winner_id,
        c.is_tie,
        c.decision_time_ms
    FROM comparisons c
    INNER JOIN songs sa ON c.song_a_id = sa.id
    INNER JOIN songs sb ON c.song_b_id = sb.id
    WHERE sa.artist = p_artist 
      AND sb.artist = p_artist;
END;
$$;

-- 6. RPC function to get all songs for a specific artist (for BT model setup)
CREATE OR REPLACE FUNCTION get_artist_songs(p_artist TEXT)
RETURNS TABLE (
    song_id UUID,
    name TEXT,
    artist TEXT,
    global_elo FLOAT8,
    global_bt_strength FLOAT8,
    global_votes_count INT4
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        id as song_id,
        songs.name,
        songs.artist,
        songs.global_elo,
        songs.global_bt_strength,
        songs.global_votes_count
    FROM songs
    WHERE songs.artist = p_artist;
END;
$$;

-- 7. RPC function to bulk update global rankings (high performance)
CREATE OR REPLACE FUNCTION bulk_update_song_rankings(
    p_song_ids UUID[],
    p_global_elos FLOAT8[],
    p_global_bt_strengths FLOAT8[],
    p_global_votes INT4[]
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE songs s
    SET 
        global_elo = new_values.global_elo,
        global_bt_strength = new_values.global_bt_strength,
        global_votes_count = new_values.global_votes_count
    FROM unnest(
        p_song_ids, 
        p_global_elos, 
        p_global_bt_strengths, 
        p_global_votes
    ) AS new_values(song_id, global_elo, global_bt_strength, global_votes_count)
    WHERE s.id = new_values.song_id;
END;
$$;

-- 8. Comment documentation
COMMENT ON COLUMN songs.global_elo IS 'Platform-wide Elo rating computed from all user sessions';
COMMENT ON COLUMN songs.global_bt_strength IS 'Bradley-Terry strength parameter used in global ranking calculations';
COMMENT ON COLUMN songs.global_votes_count IS 'Total number of comparisons this song has participated in globally';
COMMENT ON TABLE artist_stats IS 'Tracks when each artist last had their global leaderboard recalculated';
