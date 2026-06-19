# ADR-002 — Durable Mission Orchestrator

**Status:** Decided — Defer external framework, harden homegrown engine  
**Date:** 2026-06-20  
**Authors:** consolidation T5.5  

---

## Context

Béa's mission orchestrator (`core/meta_orchestrator.py`, 1973 lines) is a homegrown async engine. It lacks durable checkpointing: if the process crashes mid-mission, there is no replay log — the mission is lost or stuck in READY. Three alternatives were evaluated:

1. **Keep homegrown** — the current engine, hardened with persistence hooks  
2. **LangGraph** (LangChain ecosystem) — Python graph-based state machine with optional persistence  
3. **Temporal** — full workflow durability platform (Go daemon, Python SDK)  

---

## Options evaluated

### Option 1 — Homegrown engine with persistence hooks (CHOSEN)

**What we have now:**  
- `MetaOrchestrator.run_mission()` is fully async; phases are sequential Python  
- Mission state is persisted to Postgres via `MissionSystem`  
- On restart, READY missions can be re-queued by `api/main.py` lifespan  
- No replay: if a phase crashes, the mission shows `IN_PROGRESS` forever (ghost state)  

**Hardening plan (incremental, no new dep):**
1. Phase checkpoints: write `phase_cursor` to Postgres at each phase boundary  
2. Crash recovery: on startup, re-queue `IN_PROGRESS` missions from `phase_cursor`  
3. Idempotent phases: each phase checks if already done before re-executing  

**Cost:** ~200 lines in `meta_orchestrator.py` + a DB migration  
**Risk:** Low — incremental, same tech stack  

### Option 2 — LangGraph

**Pros:** Python, graph-based (maps cleanly to our phase structure), optional persistence via `langgraph-checkpoint-postgres`  
**Cons:**  
- 823 files renamed from jarvis→bea; another refactor-scope change right now adds churn  
- LangGraph has its own state schema (`TypedDict`); migrating 12 phases would require significant rewrite  
- Version lock to LangChain ecosystem (we deliberately avoided this for LLM routing)  
- `langgraph` adds ~15 MB deps  

**Verdict:** Not now. Revisit if homegrown hardening proves insufficient.  

### Option 3 — Temporal

**Pros:** Best-in-class durability, replays, versioning, long-running workflows  
**Cons:**  
- Requires a Temporal server (Go daemon) — new infra on Windows + Railway  
- Python SDK is mature but adds 8–12 dep packages  
- Full migration of 12 phases to Temporal workflows = multi-week effort  
- Overkill for Béa's current load (< 100 concurrent missions)  

**Verdict:** Future option when Béa reaches scale requiring production-grade SLAs.  

---

## Decision

**Stick with homegrown, add phase checkpointing.**

The key insight: the ghost-state bug (missions stuck IN_PROGRESS forever) is already partially fixed by the terminal-state truth work (Sprint 3). The remaining gap is crash recovery during active execution.

The increment is small and low-risk: add a `phase_cursor` column to the missions table, write it at each phase boundary in `meta_orchestrator.py`, and add a recovery loop at startup. No new dependencies. Compatible with the current Railway + Postgres deployment.

LangGraph and Temporal remain on the radar. The right trigger for LangGraph is if we want visual graph inspection of mission execution. The right trigger for Temporal is if Béa runs multi-day missions or needs exactly-once guarantees.

---

## Consequences

- **Short term (sprint N):** Add `phase_cursor` migration + checkpoint writes. Target: ghost-state rate → 0.  
- **Medium term:** Evaluate LangGraph if we want visual mission graph editor in the cockpit.  
- **Long term:** Temporal if Béa graduates to SLA-bound enterprise workflows.  
- **This ADR is NOT binding beyond its decision date.** If circumstances change (new team, scale, external integrations), revisit.
