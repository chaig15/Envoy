-- Add table_type column to snipes for targeting specific seating types
-- Examples: "Dining Room", "Bar", "Patio", "Butter Chicken", "Tasting Menu"

ALTER TABLE snipes ADD COLUMN table_type VARCHAR(100);

-- Optional: Index for filtering by table_type if we ever need to query by it
-- CREATE INDEX idx_snipes_table_type ON snipes (table_type) WHERE table_type IS NOT NULL;

