-- Migration 001: Initialize Core Schema
-- BeaMax Phase 0 - Bootstrap database
-- PostgreSQL 13+ compatible
-- Run date: 2026-04-10

BEGIN;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search

-- Create canonical_missions table (core mission state)
CREATE TABLE IF NOT EXISTS canonical_missions (
    mission_id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'WRITE_LOW',
    error TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    source_system TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    context_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE canonical_missions IS 'Core mission tracking - canonical state for all BeaMax missions';
COMMENT ON COLUMN canonical_missions.risk_level IS 'Risk level: READ_ONLY, WRITE_LOW, WRITE_HIGH';
COMMENT ON COLUMN canonical_missions.status IS 'Mission status: pending, running, completed, failed, cancelled';
COMMENT ON COLUMN canonical_missions.context_json IS 'Mission context and metadata (serialized JSON)';

-- Create indexes for canonical_missions
CREATE INDEX IF NOT EXISTS idx_canonical_missions_status ON canonical_missions(status);
CREATE INDEX IF NOT EXISTS idx_canonical_missions_created_at ON canonical_missions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_missions_source_system ON canonical_missions(source_system);
CREATE INDEX IF NOT EXISTS idx_canonical_missions_risk_level ON canonical_missions(risk_level);

-- Create migration history table
CREATE TABLE IF NOT EXISTS migration_history (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    execution_time_ms INTEGER
);

COMMENT ON TABLE migration_history IS 'Track applied database migrations';

-- Record this migration
INSERT INTO migration_history (migration_name, success, execution_time_ms)
VALUES ('001_init_schema', true, 0)
ON CONFLICT (migration_name) DO NOTHING;

COMMIT;

-- Verify migration success
SELECT 
    'Migration 001 completed successfully' AS status,
    COUNT(*) AS total_tables
FROM information_schema.tables
WHERE table_schema = 'public' 
  AND table_name IN ('canonical_missions', 'migration_history');
