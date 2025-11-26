-- Add model field to track which LLM model was used

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS model TEXT;

