# LLM Router Consolidation Plan

**DATE:** 2026-04-10  
**STATUS:** Audit phase  
**TARGET:** 9 routers → 1 unified routing system

---

## Current State (2470 lines total)

| Router | Lines | Purpose | Status |
|--------|-------|---------|--------|
| **core/model_router.py** | 108 | Route to Claude/GPT/Llama models | 🟢 Core — keep as base |
| **core/task_router.py** | 360 | Route tasks to agents (supervisor pattern) | 🟡 Refactor → agent selector |
| **core/domain_router.py** | 128 | Domain detection (code/data/research) | 🟡 Merge into classifier |
| **core/dynamic_agent_router.py** | 430 | Dynamic agent scoring + allocation | 🟠 Complex — audit before merge |
| **core/adaptive_routing.py** | 588 | Health tracking + cost optimization | 🟢 Production-critical — keep |
| **core/llm_routing_policy.py** | 596 | Budget/latency policy engine | 🟢 Production-critical — keep |
| **core/capability_routing/router.py** | 260 | Route by capability to providers | 🟡 Merge into model_router |
| **core/capabilities/semantic_router.py** | ? | Semantic intent routing | 🔍 Review (not yet analyzed) |
| **core/skills/security_skill_router.py** | ? | Security skill dispatch | 🟡 Move to skill system |
| **core/skills/domain_skill_router.py** | ? | Domain skill dispatch | 🟡 Move to skill system |

---

## Problems Identified

1. **Overlapping responsibilities:**
   - `model_router` + `capability_routing/router` both route to models
   - `domain_router` + `task_router` both classify tasks
   - `dynamic_agent_router` + `task_router` both select agents

2. **Circular dependencies risk:**
   - Multiple routers may import each other
   - No clear single entry point

3. **Test fragmentation:**
   - 5+ test files for routing (test_task_router, test_model_router, test_domain_routing_integration, test_openrouter_routing, test_kernel_routing)
   - Each tests a different slice → hard to validate consolidation

4. **Configuration scattered:**
   - routing.yaml (if exists?)
   - model_registry.yaml
   - kernel_registry.yaml
   - No single routing config

---

## Consolidation Strategy (3 phases)

### **Phase 1 — Audit & Mapping (Session 4)** ✅ DONE
- [x] Locate all routers
- [x] Count lines + identify interfaces
- [x] Map dependencies (imports between routers)
- [ ] Run existing router tests to establish baseline

### **Phase 2 — Simplify Interfaces (Week 2)**
1. **Keep 3 production routers:**
   - `model_router.py` (base model selection)
   - `adaptive_routing.py` (health + cost tracking)
   - `llm_routing_policy.py` (policy engine)

2. **Merge into model_router:**
   - `capability_routing/router.py` → add capability-based dispatch
   - `domain_router.py` → add domain classification helper

3. **Refactor task/agent routing:**
   - `task_router.py` → extract agent selector into `core/orchestration/agent_selector.py`
   - `dynamic_agent_router.py` → merge scoring into agent_selector

4. **Move skill routers:**
   - `core/skills/*_router.py` → integrate into skill system (not routing layer)

### **Phase 3 — Unified Entry Point (Week 3)**
Create `core/unified_router.py` (single public API):

```python
from core.model_router import ModelRouter
from core.adaptive_routing import get_enhanced_tracker
from core.llm_routing_policy import RoutingPolicy

class UnifiedRouter:
    """
    Single entry point for all LLM/agent routing.
    
    Responsibilities:
    - Model selection (model_router)
    - Health tracking (adaptive_routing)
    - Policy enforcement (llm_routing_policy)
    - Agent allocation (agent_selector)
    """
    
    def route_model(self, task, budget_mode, latency_mode): ...
    def route_agent(self, task, available_agents): ...
    def select_kernel(self, mission): ...
```

**Result:** 
- 9 files → 4 files (unified_router + 3 backends)
- 2470 lines → ~1200 lines (-52%)
- Single import: `from core.unified_router import UnifiedRouter`

---

## Testing Strategy

### Regression Suite
1. Run all `tests/test_*router*.py` BEFORE consolidation → save results
2. After each merge, re-run same tests with compatibility shims
3. Final validation: all original tests passing through unified_router

### Performance Benchmarks
- Baseline routing latency (current): ~?ms p95
- Target after consolidation: <50ms p95 (model_router should be fast)

---

## Non-Goals (Out of Scope)

- **Semantic router analysis:** Deferred until Phase 2 (unclear if production-used)
- **Skill routing redesign:** Separate work (skill system refactor)
- **New routing algorithms:** Focus on consolidation, not feature additions

---

## Risks

| Risk | Mitigation |
|------|------------|
| Breaking existing missions | Keep old routers as deprecated shims for 1 release |
| Performance regression | Benchmark before/after, rollback if >20% slower |
| Circular import hell | Use dependency injection, not direct imports |
| Lost functionality | Audit each router's unique features before merge |

---

## Success Metrics

- ✅ 9 routers → 4 files
- ✅ 2470 lines → ~1200 lines (-52%)
- ✅ All existing routing tests passing
- ✅ Single import entry point
- ✅ No performance regression (routing latency <50ms p95)

---

## Next Steps (Session 5)

1. Run router test baseline:
   ```bash
   pytest tests/test_*router*.py -v > router_tests_baseline.txt
   ```

2. Map import dependencies:
   ```bash
   grep -r "^from core.*router\|^import core.*router" core/ > router_deps.txt
   ```

3. Start Phase 2: Merge capability_routing → model_router (smallest merge first)

---

**DECISION POINT:** After audit, decide if 9 → 4 is realistic or if 9 → 6 is safer first step.

**BUDGET:** 2-3 weeks for full consolidation (Phase 2-3), ~6-8 hours per week.
