# Major Technical Debt Map

Files flagged for eventual refactor. Listed in priority order.
Each entry has: current state, risk, and migration path.

---

## 1. `core/bea_executor.py` — 1295 L (DEPRECATED)

**Status:** Kept for backward compatibility only.
**Replaced by:** `core.meta_orchestrator.MetaOrchestrator`

**Internal sections** (already annotated with `# ──` markers):

| Section | Approx. lines | Contents |
|---------|---------------|----------|
| Module constants | 1–50 | `SESSION_TIMEOUTS`, `INTENT_MAP` |
| `__init__` | 51–103 | lazy attribute stubs, background task set |
| Lazy properties | 104–308 | 15 components (agents, risk, memory, LLM, …) |
| Intent/complexity | 309–359 | `classify_intent`, `_compute_mission_complexity` |
| Public API | 360–412 | `run()` — entry point, timeout wrapper |
| Dispatch | 413–425 | `_dispatch()` — mode router |
| AUTO pipeline | 426–650 | `_run_auto` — HierarchicalPlanner + AtlasDirector + agent loop |
| CHAT pipeline | 651–750 | `_run_chat` — direct LLM, no tool use |
| NIGHT pipeline | 751–820 | `_run_night` — multi-cycle long-horizon |
| IMPROVE pipeline | 821–890 | `_run_improve` — self-improvement loop |
| WORKFLOW pipeline | 891–960 | `_run_workflow` — structured workflow execution |
| Tool/action loop | 961–1150 | `_execute_actions`, tool dispatch, approval |
| Result handling | 1151–1295 | `_finalize_session`, memory persistence |

**Migration plan:**
1. Inline `SESSION_TIMEOUTS` and `INTENT_MAP` into `MetaOrchestrator` (constants only).
2. Move lazy properties into `MetaOrchestrator._components` dict (already partially done).
3. Move pipeline methods (`_run_auto`, `_run_chat`, …) into `core/pipelines/` sub-package.
4. Delete this file; update `core/orchestrator.py` re-exports to point at MetaOrchestrator.

**Blocker:** `MetaOrchestrator` currently delegates to `BeaOrchestrator` — cannot delete until delegation is fully eliminated. Track in a dedicated PR.

---

## 2. `api/main.py` — 347 L ✅ (refactored 2026-06-14)

**Status:** RESOLVED — router mounting extracted to `api/router_mount.py`.
Previous size: 795 L. Now: ~347 L focused on app setup, middleware, and inline endpoints.

**Remaining inline items** (acceptable; not worth further splitting):
- `/api/v2/session` endpoint (19 L) — mobile app role detection
- `TaskRequest` / `ModeRequest` Pydantic models — used by routes imported elsewhere
- `_run_mission`, `_get_orchestrator`, and lazy component getters — thin wrappers

---

## 3. `core/workflow_runtime.py` — 101 L (thin wrapper) ✅

**Status:** RESOLVED — split into `core/workflow/` sub-package (PR #56).
Wrapper re-exports all symbols for backward compat.

---

## Guidelines for future debt

- Files **> 800 L** that aren't thin wrappers → open a split ticket before adding more code.
- Deprecated modules must emit `DeprecationWarning` on instantiation (already done for `BeaOrchestrator`).
- New pipelines → `core/pipelines/<mode>.py`, not added to `bea_executor.py`.
