-- 1. Add column to comparisons table
ALTER TABLE comparisons 
ADD COLUMN IF NOT EXISTS decision_time_ms INTEGER;

-- 2. Update the RPC function to handle the new column
CREATE OR REPLACE FUNCTION record_duel(
    p_session_id UUID,
    p_song_a_id UUID,
    p_song_b_id UUID,
    p_winner_id UUID,
    p_is_tie BOOLEAN,
    p_new_elo_a FLOAT,
    p_new_elo_b FLOAT,
    p_decision_time_ms INTEGER DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Insert the comparison record
    INSERT INTO comparisons (
        session_id, 
        song_a_id, 
        song_b_id, 
        winner_id, 
        is_tie, 
        decision_time_ms
    ) VALUES (
        p_session_id,
        p_song_a_id,
        p_song_b_id,
        p_winner_id,
        p_is_tie,
        p_decision_time_ms
    );

    -- Update Song A local_elo
    UPDATE session_songs
    SET local_elo = p_new_elo_a
    WHERE session_id = p_session_id AND song_id = p_song_a_id;

    -- Update Song B local_elo
    UPDATE session_songs
    SET local_elo = p_new_elo_b
    WHERE session_id = p_session_id AND song_id = p_song_b_id;
END;
$$;
