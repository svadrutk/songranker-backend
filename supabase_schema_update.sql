-- Update songs table
ALTER TABLE songs ADD COLUMN IF NOT EXISTS isrc TEXT;
ALTER TABLE songs ADD COLUMN IF NOT EXISTS genres TEXT[];

-- Create index for ISRC for efficient upserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_songs_isrc ON songs(isrc) WHERE isrc IS NOT NULL;

-- Update sessions table
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS playlist_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS playlist_name TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS source_platform TEXT DEFAULT 'manual';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS collection_metadata JSONB DEFAULT '{}'::jsonb;

-- Update get_user_session_summaries RPC to return new fields
-- Note: You may need to drop and recreate the function depending on its definition
-- This is a template for the expected output columns
/*
CREATE OR REPLACE FUNCTION get_user_session_summaries(p_user_id uuid)
RETURNS TABLE (
    out_session_id uuid,
    out_created_at timestamptz,
    out_primary_artist text,
    out_playlist_name text,
    out_song_count bigint,
    out_comparison_count bigint,
    out_convergence_score integer,
    out_top_album_covers text[]
) AS $$
...
$$ LANGUAGE plpgsql;
*/
