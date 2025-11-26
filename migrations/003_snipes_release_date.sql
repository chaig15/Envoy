-- Add release_date column to snipes
-- release_date = the day the snipe should EXECUTE (when reservations open)
-- target_date = the day user wants the reservation FOR

ALTER TABLE snipes ADD COLUMN IF NOT EXISTS release_date DATE;

-- Backfill: assume same-day for existing snipes (conservative)
UPDATE snipes SET release_date = target_date WHERE release_date IS NULL;

-- Make it required going forward
ALTER TABLE snipes ALTER COLUMN release_date SET NOT NULL;

-- Update index to use release_date
DROP INDEX IF EXISTS idx_snipes_pending;
CREATE INDEX IF NOT EXISTS idx_snipes_pending ON snipes(status, release_date) WHERE status = 'pending';

