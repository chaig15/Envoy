-- Add table_type column to watches for targeting specific seating types
-- Examples: "Dining Room", "Bar", "Patio", "Butter Chicken", "Tasting Menu"

ALTER TABLE watches ADD COLUMN table_type VARCHAR(100);

