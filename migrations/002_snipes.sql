-- Snipes table for scheduled reservation sniping at release time

CREATE TABLE IF NOT EXISTS snipes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    venue_id INTEGER NOT NULL,
    venue_name TEXT NOT NULL,
    target_date DATE NOT NULL,
    party_size INTEGER NOT NULL,
    release_time TIME DEFAULT '09:00',
    release_timezone TEXT DEFAULT 'America/New_York',
    status TEXT DEFAULT 'pending',  -- pending, sniping, success, failed, cancelled
    result_reservation_id TEXT,
    result_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE
);

-- Index for finding pending snipes due to execute
CREATE INDEX IF NOT EXISTS idx_snipes_pending ON snipes(status, target_date) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_snipes_user_id ON snipes(user_id);

