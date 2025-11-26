-- Conversation history for LLM context persistence

CREATE TABLE IF NOT EXISTS conversations (
    telegram_id BIGINT PRIMARY KEY,
    messages JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for cleanup of old conversations
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);

