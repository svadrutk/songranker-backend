ALTER TABLE songs ADD COLUMN IF NOT EXISTS apple_music_id TEXT;
CREATE INDEX IF NOT EXISTS idx_songs_apple_music_id ON songs (apple_music_id);
