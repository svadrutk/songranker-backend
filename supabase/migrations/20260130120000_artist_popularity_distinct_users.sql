-- ============================================
-- Artist popularity: distinct users per artist
-- ============================================
-- For "most popular artist" we count at most one contribution per user per artist.
-- This RPC returns artists with leaderboards ordered by distinct user count.

CREATE OR REPLACE FUNCTION get_artists_leaderboard_popularity(p_limit INT DEFAULT 50)
RETURNS TABLE (
    artist TEXT,
    distinct_users_count BIGINT,
    last_global_update_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
AS $$
  WITH comparison_users AS (
    SELECT DISTINCT s.user_id, sa.artist
    FROM comparisons c
    INNER JOIN sessions s ON c.session_id = s.id
    INNER JOIN songs sa ON c.song_a_id = sa.id
    INNER JOIN songs sb ON c.song_b_id = sb.id
    WHERE sa.artist = sb.artist
  ),
  artist_counts AS (
    SELECT cu.artist, COUNT(*)::BIGINT AS distinct_users_count
    FROM comparison_users cu
    GROUP BY cu.artist
  )
  SELECT ac.artist, ac.distinct_users_count, ast.last_global_update_at
  FROM artist_counts ac
  INNER JOIN artist_stats ast ON ast.artist = ac.artist
  ORDER BY ac.distinct_users_count DESC
  LIMIT p_limit;
$$;

COMMENT ON FUNCTION get_artists_leaderboard_popularity(INT) IS
  'Artists with leaderboards ordered by distinct users who have ranked that artist (one comparison per user per artist counts).';
