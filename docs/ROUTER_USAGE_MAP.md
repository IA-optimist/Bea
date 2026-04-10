# Router Usage Map — Production Analysis

**DATE:** 2026-04-10  
**PURPOSE:** Identify which routers are production-critical vs test-only

---

## Router Classification

| Router | Status | Production Usage | Lines | Action |
|--------|--------|------------------|-------|--------|
| **core/adaptive_routing.py** | 🟢 PROD | MetaOrchestrator health tracking | 588 | KEEP |
| **core/llm_routing_policy.py** | 🟢 PROD | Budget/latency policy | 596 | KEEP |
| **core/capability_routing/router.py** | 🟢 PROD | Capability-based provider selection | 260 | KEEP |
| **core/domain_router.py** | 🟢 PROD | mission_system.py, skill routers | 128 | KEEP |
| **core/task_router.py** | 🟡 PARTIAL | Agent selection logic | 360 | REFACTOR |
| **core/dynamic_agent_router.py** | 🔍 UNKNOWN | Dynamic scoring (usage unclear) | 430 | AUDIT |
| **core/model_router.py** | 🔴 TEST-ONLY | Never imported in core/ | 108 | DEPRECATE |
| **core/skills/security_skill_router.py** | 🟡 SKILL | Extends BaseDomainRouter | ? | Move to skill system |
| **core/skills/domain_skill_router.py** | 🟡 SKILL | Base class for skill routing | ? | Move to skill system |

---

## Import Analysis

### Production Imports (core/)

```bash
# adaptive_routing.py
core/meta_orchestrator.py:        from core.adaptive_routing import get_enhanced_tracker

# llm_routing_policy.py
(used via adaptive_routing — indirect)

# capability_routing/router.py
core/meta_orchestrator.py:        from core.capability_routing.router import route_mission

# domain_router.py
core/mission_system.py:            from core.domain_router import get_domain_router
core/orchestrator_lg/langgraph_flow.py:        from core.domain_router import classify_domain

# task_router.py
(grep shows test imports only — production usage unclear)

# dynamic_agent_router.py
core/meta_orchestrator.py:            from core.dynamic_agent_router import route_agents
```

### Test-Only Imports

```bash
# model_router.py
tests/test_model_router.py  (16 tests)
NO production imports found in core/
```

---

## Consolidation Strategy (REVISED)

### ❌ ORIGINAL PLAN (too risky):
- 9 routers → 4 files
- Merge capability_routing + model_router

### ✅ REVISED PLAN (safer):

**Phase 1 — Dead Code Cleanup (Session 5)**
- [x] Mark `model_router.py` as DEPRECATED (test-only)
- [ ] Archive `orchestrator_lg/` (LangGraph alternate orchestrator, unused?)
- [ ] Audit `dynamic_agent_router.py` usage in production

**Phase 2 — Interface Simplification (Week 2)**
- Extract agent selection from `task_router.py` → `core/orchestration/agent_selector.py`
- Move skill routers to `core/skills/routing/` (clearer organization)
- Create `core/routing/__init__.py` as single import entry point:
  ```python
  from core.adaptive_routing import get_enhanced_tracker
  from core.llm_routing_policy import RoutingPolicy
  from core.capability_routing.router import route_mission
  from core.domain_router import get_domain_router, detect_domain
  ```

**Phase 3 — Unified API (Week 3)**
- Create `core/routing/unified.py` facade (optional convenience layer)
- NOT a rewrite — just a thin wrapper over existing routers
- Goal: Single import for common patterns, not force migration

---

## Rationale for Revised Plan

1. **Risk reduction:** Don't merge production routers with different responsibilities
2. **Test compatibility:** Keep deprecated routers for test suite (avoid rewriting 65 tests)
3. **Gradual migration:** Facade pattern allows opt-in migration, not forced refactor
4. **Production stability:** Current routing works — focus on clarity, not consolidation

---

## Success Metrics (Revised)

- ✅ Clear deprecation markers on dead code
- ✅ Centralized import path (core/routing/)
- ✅ Documentation of which router does what
- ❌ ~~Line count reduction~~ (not a goal anymore — clarity > brevity)
- ✅ All existing tests still passing

---

## Next Steps

1. ✅ Mark model_router.py as deprecated (DONE)
2. Audit dynamic_agent_router.py production usage
3. Check if orchestrator_lg/ is active (LangGraph flow)
4. Create core/routing/ namespace (Phase 2)

---

**LESSON LEARNED:** Consolidation for consolidation's sake is risky. Focus on **clarity** and **dead code removal** over **line count reduction**.
