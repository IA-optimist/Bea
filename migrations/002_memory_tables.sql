-- Migration 002: Memory Tables
-- JarvisMax Phase 0 - Memory and knowledge storage
-- PostgreSQL 13+ compatible
-- Run date: 2026-04-10

BEGIN;

-- Create vault_memory table (long-term memory store)
CREATE TABLE IF NOT EXISTS vault_memory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memory_type VARCHAR(50) NOT NULL,  -- 'mission', 'knowledge', 'improvement', 'tool', etc.
    key TEXT NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags TEXT[] DEFAULT '{}',
    embedding VECTOR(1536),  -- For semantic search (optional — requires pgvector)
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE vault_memory IS 'Long-term memory vault - knowledge, mission history, improvements';
COMMENT ON COLUMN vault_memory.memory_type IS 'Memory category: mission, knowledge, improvement, tool, domain';
COMMENT ON COLUMN vault_memory.key IS 'Unique identifier within memory_type namespace';
COMMENT ON COLUMN vault_memory.value IS 'Memory payload (arbitrary JSON structure)';
COMMENT ON COLUMN vault_memory.tags IS 'Searchable tags for filtering and retrieval';
COMMENT ON COLUMN vault_memory.embedding IS 'Optional semantic embedding for vector search';

-- Create indexes for vault_memory
CREATE INDEX IF NOT EXISTS idx_vault_memory_type ON vault_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_vault_memory_key ON vault_memory(key);
CREATE INDEX IF NOT EXISTS idx_vault_memory_tags ON vault_memory USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_vault_memory_created_at ON vault_memory(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vault_memory_accessed_at ON vault_memory(accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_vault_memory_type_key ON vault_memory(memory_type, key);

-- Create users table (for auth, JWT, API tokens)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',  -- admin, user, viewer
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login_at TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE users IS 'User accounts for authentication and authorization';
COMMENT ON COLUMN users.role IS 'RBAC role: admin, user, viewer';
COMMENT ON COLUMN users.metadata IS 'Extended user metadata (preferences, permissions, etc.)';

-- Create indexes for users
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- Create access_tokens table (JWT, API tokens)
CREATE TABLE IF NOT EXISTS access_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_type VARCHAR(50) NOT NULL DEFAULT 'bearer',  -- bearer, api_key, refresh
    expires_at TIMESTAMP WITH TIME ZONE,
    is_revoked BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE access_tokens IS 'Active access tokens for API authentication';
COMMENT ON COLUMN access_tokens.token_hash IS 'Hashed token (never store plaintext)';
COMMENT ON COLUMN access_tokens.token_type IS 'Token type: bearer (JWT), api_key (static), refresh';

-- Create indexes for access_tokens
CREATE INDEX IF NOT EXISTS idx_access_tokens_user_id ON access_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_access_tokens_token_hash ON access_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_access_tokens_expires_at ON access_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_access_tokens_is_revoked ON access_tokens(is_revoked);

-- Create updated_at triggers
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vault_memory_updated_at
    BEFORE UPDATE ON vault_memory
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Record this migration
INSERT INTO migration_history (migration_name, success, execution_time_ms)
VALUES ('002_memory_tables', true, 0)
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- Verify migration success
SELECT 
    'Migration 002 completed successfully' AS status,
    COUNT(*) AS total_tables
FROM information_schema.tables
WHERE table_schema = 'public' 
  AND table_name IN ('vault_memory', 'users', 'access_tokens');
