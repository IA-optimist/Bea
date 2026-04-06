-- ================================================================
-- JARVIS MAX - Init PostgreSQL
-- Created automatically on first docker compose startup.
--
-- ALIGNED with core/db.py SQLite schema + asyncpg module schemas.
-- Last aligned: 2026-04-06 (audit reconciliation Phase 1)
-- ================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector for embeddings

-- ═══════════════════════════════════════════════════════════════
-- TABLES MATCHING core/db.py (SQLite equivalent)
-- These are the primary application tables.
-- ═══════════════════════════════════════════════════════════════

-- Vault entries (matches SQLite vault_entries in core/db.py)
CREATE TABLE IF NOT EXISTS vault_entries (
    id          TEXT PRIMARY KEY,
    type        TEXT,
    content     TEXT,
    source      TEXT,
    confidence  REAL,
    usage_count INTEGER DEFAULT 0,
    last_used   TEXT,
    tags        TEXT,
    related_to  TEXT,
    valid       INTEGER DEFAULT 1,
    created_at  REAL,
    expires_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_vault_id   ON vault_entries(id);
CREATE INDEX IF NOT EXISTS idx_vault_type ON vault_entries(type);

-- Actions (matches SQLite actions in core/db.py)
CREATE TABLE IF NOT EXISTS actions (
    id            TEXT PRIMARY KEY,
    description   TEXT,
    risk          TEXT,
    target        TEXT,
    impact        TEXT,
    diff          TEXT,
    rollback      TEXT,
    mission_id    TEXT,
    status        TEXT DEFAULT 'PENDING',
    created_at    REAL,
    approved_at   REAL,
    rejected_at   REAL,
    executed_at   REAL,
    result        TEXT DEFAULT '',
    note          TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_actions_mission  ON actions(mission_id);
CREATE INDEX IF NOT EXISTS idx_actions_status   ON actions(status);

-- Missions (matches SQLite missions in core/db.py)
CREATE TABLE IF NOT EXISTS missions (
    id                    TEXT PRIMARY KEY,
    user_input            TEXT,
    intent                TEXT,
    status                TEXT,
    plan_summary          TEXT,
    plan_steps            TEXT,
    advisory_score        REAL DEFAULT 0,
    advisory_decision     TEXT DEFAULT 'UNKNOWN',
    advisory_issues       TEXT,
    advisory_risks        TEXT,
    action_ids            TEXT,
    requires_validation   INTEGER DEFAULT 1,
    auto_approved         INTEGER DEFAULT 0,
    created_at            REAL,
    updated_at            REAL,
    completed_at          REAL,
    note                  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status);

-- Goals (matches SQLite goals in core/db.py)
CREATE TABLE IF NOT EXISTS goals (
    id        TEXT PRIMARY KEY,
    text      TEXT,
    mode      TEXT,
    priority  INTEGER DEFAULT 2,
    status    TEXT DEFAULT 'ACTIVE',
    created_at REAL,
    updated_at REAL
);

-- ═══════════════════════════════════════════════════════════════
-- TABLES CREATED BY asyncpg MODULES
-- These are created by Python code but should exist at init.
-- ═══════════════════════════════════════════════════════════════

-- DAG checkpoints (core/orchestrator_v2.py)
CREATE TABLE IF NOT EXISTS dag_checkpoints (
    dag_id     TEXT NOT NULL,
    node_id    TEXT NOT NULL,
    status     TEXT DEFAULT 'pending',
    result     TEXT,
    error      TEXT,
    started_at TIMESTAMPTZ,
    ended_at   TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (dag_id, node_id)
);

-- Improvement entries (core/improvement_memory.py)
CREATE TABLE IF NOT EXISTS improvement_entries (
    id          SERIAL PRIMARY KEY,
    category    TEXT NOT NULL,
    description TEXT,
    source      TEXT,
    status      TEXT DEFAULT 'pending',
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Vector embeddings (memory/vector_store.py) — requires pgvector
CREATE TABLE IF NOT EXISTS embeddings (
    id         SERIAL PRIMARY KEY,
    content    TEXT NOT NULL,
    embedding  vector(1536),
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_meta ON embeddings USING GIN(metadata);

-- ═══════════════════════════════════════════════════════════════
-- OPERATIONAL TABLES (Postgres-only, for production monitoring)
-- ═══════════════════════════════════════════════════════════════

-- Sessions (production tracking)
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    mode          TEXT,
    mission       TEXT,
    final_report  TEXT,
    status        TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Runtime config (key-value store for dynamic settings)
CREATE TABLE IF NOT EXISTS runtime_config (
    key        VARCHAR(128) PRIMARY KEY,
    value      JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════════
-- TRIGGERS
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to tables with updated_at
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'improvement_entries_updated_at') THEN
        CREATE TRIGGER improvement_entries_updated_at
            BEFORE UPDATE ON improvement_entries
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
    END IF;
END;
$$;
