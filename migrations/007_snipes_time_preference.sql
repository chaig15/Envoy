-- Add time preference columns to snipes for targeting specific time windows
-- Same approach as watches: time_earliest and time_latest define the window

ALTER TABLE snipes ADD COLUMN time_earliest TIME;
ALTER TABLE snipes ADD COLUMN time_latest TIME;

-- Note: When both are NULL, sniper will try prime time (7-8pm) first,
-- then fall back to any available slot.

