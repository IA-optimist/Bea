# Database Reconciliation Plan: SQLite vs PostgreSQL

**Date:** 2026-04-06 | **Status:** DRAFT | **Priority:** P1

## Current State

JarvisMax has TWO independent database systems with **different schemas**:

### SQLite (`core/db.py`)
- Path: `workspace/jarvismax.db`
- Always available, no external dependency
- Used as fallback when Postgres unavailable

| Table | Columns | Used by |
|-------|---------|---------|
| `vault_entries` | key, value, category, created_at, updated_at | vault_memory.py |
| `actions` | id, session_id, action_type, payload, result, status, created_at | orchestrator_v2.py (fallback) |
| `missions` | id, title, status, plan_json, result_json, created_at, updated_at | orchestrator_v2.py (fallback) |
| `goals` | id, mission_id, description, status, created_at | orchestrator_v2.py (fallback) |

### PostgreSQL (`docker/postgres/init.sql`)
- DSN: from `DATABASE_URL` env var (currently NOT SET in settings)
- Requires Docker or external Postgres instance

| Table | Columns | Used by |
|-------|---------|---------|
| `vault_memory` | id, key, value, category, metadata, created_at, updated_at, expires_at | (init.sql only — no Python code uses this table name) |
| `action_log` | id, session_id, action_type, input_data, output_data, status, duration_ms, error, created_at | (init.sql only) |
| `sessions` | id, user_id, status, metadata, started_at, ended_at | (init.sql only) |
| `runtime_config` | key, value, updated_at, updated_by | (init.sql only) |

### asyncpg Usage (Python code creating their OWN tables)
- `core/orchestrator_v2.py` → creates `dag_checkpoints` table in Postgres
- `core/improvement_memory.py` → creates `improvement_entries` table in Postgres
- `memory/vector_store.py` → creates `embeddings` table with pgvector
- `memory/store.py` → uses pg_pool for memory operations

## Key Problems

1. **Table names don't match**: SQLite `vault_entries` ≠ Postgres `vault_memory`, `actions` ≠ `action_log`
2. **Schema mismatch**: Postgres tables have extra columns (metadata, expires_at, duration_ms)
3. **init.sql tables are UNUSED**: No Python code references `vault_memory`, `action_log`, `sessions`, or `runtime_config` by name
4. **DATABASE_URL is NOT SET**: `get_settings()` returns `database_url=None` — Postgres is declared but never connected
5. **Each module creates its own tables**: orchestrator_v2, improvement_memory, vector_store all do their own `CREATE TABLE`
6. **No migration system**: No Alembic, no versioned migrations

## Migration Plan

### Phase 1: Align init.sql to match actual usage (LOW RISK)
- Rename `vault_memory` → `vault_entries` in init.sql
- Rename `action_log` → `actions` in init.sql  
- Add `missions` and `goals` tables to init.sql
- Add `dag_checkpoints`, `improvement_entries`, `embeddings` tables
- Keep all extra Postgres columns (metadata, expires_at, etc.)

### Phase 2: Set DATABASE_URL properly (LOW RISK)
- Add `DATABASE_URL` to `.env.example` and `.env.production.example`
- Ensure `config/settings.py` exposes it correctly
- Test that asyncpg modules can connect

### Phase 3: Migrate SQLite reads to Postgres (MEDIUM RISK)
- `vault_memory.py`: switch from SQLite `get_db()` to asyncpg pool
- `orchestrator_v2.py`: remove SQLite fallback paths (always use Postgres in prod)
- `improvement_memory.py`: same — promote asyncpg to primary

### Phase 4: Keep SQLite as dev-only fallback (LOW RISK)
- `core/db.py` stays but is only used when `DATABASE_URL` is not set
- Document: "SQLite = local dev, Postgres = staging/prod"
- Add startup warning if running production without DATABASE_URL

### Phase 5: Add Alembic migrations (FUTURE)
- Initialize Alembic with current schema as baseline
- All future schema changes go through migrations

## Files to Modify

| File | Change |
|------|--------|
| `docker/postgres/init.sql` | Align table names + add missing tables |
| `.env.example` | Add DATABASE_URL |
| `config/settings.py` | Ensure database_url is properly exposed |
| `core/db.py` | Add "dev-only" warning when used in production |
| `memory/vault_memory.py` | Add Postgres path alongside SQLite |
| `core/orchestrator_v2.py` | Clean up dual-path logic |
| `core/improvement_memory.py` | Clean up dual-path logic |
| `main.py` | Add startup check for DATABASE_URL in prod |

## Risk Assessment

- **Phase 1-2**: Safe, documentation + config only
- **Phase 3**: Medium risk — needs thorough testing of all memory paths
- **Phase 4-5**: Future work, no urgency
