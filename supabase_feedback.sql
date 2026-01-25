-- Create feedback table for bug reports and feature requests
CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message TEXT NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    user_agent TEXT,
    url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create index for querying by creation date
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC);

-- Create index for querying by user_id
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);

-- Enable Row Level Security
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;

-- Allow anyone to insert feedback (anonymous or authenticated)
CREATE POLICY "Anyone can submit feedback"
    ON feedback
    FOR INSERT
    WITH CHECK (true);

-- Allow service role to view all feedback
CREATE POLICY "Service role can view all feedback"
    ON feedback
    FOR SELECT
    USING (auth.role() = 'service_role');
