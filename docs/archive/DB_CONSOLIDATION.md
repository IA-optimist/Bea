# DB Consolidation Plan

## Current State (as of 2026-04-11)

Two parallel DB systems coexist:

### 1. SQLite ()
- File:  (local to container)
- Tables: , , , 
- Used by: NightWorker, ActionQueue, some legacy orchestrators
- Access: , 

### 2. PostgreSQL ( → )
- Tables: , , , ,
  , , , , 
- Migrations:  (applied via )
- Used by: API routes, canonical mission system, access token management

## Problem
- No shared state between the two systems
- NightWorker reads SQLite  but API writes PostgreSQL
- Risk of divergence: mission state in SQLite ≠ PostgreSQL

## Consolidation Target (Week 2-3)
1. Migrate SQLite tables to PostgreSQL (add migrations 009+)
2. Update all SQLite callers to use PostgreSQL via SQLAlchemy
3. Remove  SQLite helpers (keep  as shim → PG)
4. Update NightWorker to read from PostgreSQL

## Interim Workaround
Both systems use different data — they don't conflict yet.
Do not mix reads/writes between them until consolidation is complete.
