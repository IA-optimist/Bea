# LLM Router Consolidation Report

## Executive Summary

**Audit Result**: Found 6 distinct LLM/routing systems with overlapping concerns. Routing architecture evolved organically with 3 layers:
1. **Task routing** (user intent → agent plan)
2. **LLM model selection** (role/context → model tier)
3. **Capability routing** (goal → provider/agent capability)

**Recommendation**: Consolidate LLM model selection into `llm_routing_policy.py` with `adaptive_routing.py` as live enhancement. Deprecate `model_router.py`. Keep capability and task routing separate (different concerns).

---

## 1. Current Router Inventory

### 1.1 LLM Model Selection Routers (PRIMARY CONSOLIDATION ZONE)

#### ✅ **core/llm_routing_policy.py** — CANONICAL LLM ROUTER (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION
- **Purpose**: AI-OS-grade dynamic model selection based on task characteristics
- **Key Features**:
  - Routes by **dimensions**: `CODE_HEAVY`, `RESEARCH_DEEP`, `MEMORY_CHEAP`, `VISION`, `CRITICAL_REASONING`, etc.
  - Scores models on: quality, cost, latency, health, context window fit
  - Budget modes: `cheap | balanced | premium`
  - Latency modes: `fast | normal | deep`
  - 8 model profiles: `orchestrator`, `heavy_coder`, `cheap_worker`, `research`, `fast_router`, `memory`, `multimodal`, `fallback`
- **Core Functions**:
  - `resolve_route(RoutingContext) → RoutingDecision`
  - `classify_dimension(ctx) → RoutingDimension`
  - `score_model(profile, dimension, ctx) → (score, reason)`
  - `ModelHealthTracker` for reliability tracking
- **Used By**:
  - Tests: 50+ test cases in `test_llm_routing_policy.py`
  - Core routing facade: `core/routing/__init__.py`
  - Documentation references
- **Lines**: 596 (comprehensive)

#### ✅ **core/adaptive_routing.py** — LIVE METRICS ENHANCEMENT (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION (monkey-patches llm_routing_policy)
- **Purpose**: Upgrades static model profiles with live performance data
- **Key Features**:
  - `LiveModelProfile` with real metrics: success rate, latency p95, cost, error spikes
  - `EnhancedHealthTracker` replaces static `ModelHealthTracker`
  - `adaptive_score_model()` blends static + live (0-100 calls ramp)
  - Self-calibrates every 50 calls from `metrics_store`
  - Error spike detection (>50% failure in last 10 calls)
  - Consecutive failure penalties
- **Core Functions**:
  - `install_adaptive_routing()` — monkey-patch installer
  - `adaptive_score_model()` — enhanced scoring with live blend
  - `get_enhanced_tracker()` — singleton tracker
  - `calibrate_profiles()` — sync with metrics_store
  - `get_fallback_recommendations()` — health-based recommendations
- **Used By**:
  - Installed at startup via `core/routing/__init__.py`
  - `core/meta_orchestrator.py` uses `get_enhanced_tracker()`
  - Tests: 15+ test cases in `test_adaptive_routing.py`
- **Lines**: 588
- **Integration**: Fail-open design (no deps broken if not installed)

#### ⚠️ **core/model_router.py** — DEPRECATED TEST STUB
- **Status**: ⚠️ TEST-ONLY, NOT USED IN PRODUCTION
- **Purpose**: Legacy tier-based routing (FAST/STANDARD/STRONG)
- **Features**:
  - Simple task_type → tier mapping
  - Complexity overrides (`trivial` → FAST, `complex` → STRONG)
  - Context size upgrades
  - Cost estimation and usage tracking
- **Core Class**: `ModelRouter` with `route()`, `record_usage()`, `estimated_savings()`
- **Used By**: ONLY `test_model_router.py` (16 test cases)
- **Lines**: 113
- **Decision**: ✅ **DEPRECATE** — functionality superseded by llm_routing_policy + adaptive_routing
- **Header Comment**: Already marked as "DEPRECATED: This router is NOT used in production"

---

### 1.2 Task/Intent Routing (SEPARATE CONCERN — KEEP)

#### ✅ **core/task_router.py** — USER INTENT CLASSIFIER (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION
- **Purpose**: Classify user messages into task modes and agent plans
- **Scope**: DIFFERENT LAYER — routes **user intent** → **agent workflow**, not LLM selection
- **Task Modes**: `CHAT`, `RESEARCH`, `PLAN`, `CODE`, `AUTO`, `NIGHT`, `IMPROVE`, `BUSINESS`
- **Output**: `RoutingDecision(mode, agents[], needs_actions, confidence)`
- **Used By**:
  - `core/jarvis_executor.py` (primary orchestrator entry point)
  - `core/context_provider.py`
  - `business/layer.py`
  - Tests: `test_task_router.py`, `test_task_router_edge.py`, `test_orchestrator.py`
- **Lines**: 360
- **Decision**: ✅ **KEEP** — handles different concern (intent classification, not model selection)

---

### 1.3 Agent Selection Routers (SEPARATE CONCERN — KEEP)

#### ✅ **core/dynamic_agent_router.py** — PERFORMANCE-BASED AGENT SELECTION (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION (feature-flagged: `JARVIS_DYNAMIC_ROUTING=1`)
- **Purpose**: Select agents using measured performance data vs static mapping
- **Scope**: Routes **mission_type** → **best agents**, not LLM selection
- **Key Features**:
  - Scores agents on: base (static), perf, domain success, tool health
  - Removes consistent underperformers
  - Boosts high performers (>75% score)
  - Multimodal detection (image/audio/document)
- **Core Functions**:
  - `route_agents(goal, mission_type, complexity, risk, static_candidates) → agents[]`
  - `get_agent_specialization_map()` — UI diagnostics
  - `get_routing_explanation()` — reasoning panel
  - `detect_multimodal_type()`, `get_multimodal_agents()`
- **Used By**:
  - `agents/crew.py` (agent selection override)
  - `core/planner.py` (routing explanation)
  - `api/routes/performance.py` (diagnostics endpoint)
  - Tests: 6+ integration tests
- **Lines**: 430
- **Decision**: ✅ **KEEP** — handles different concern (agent selection, not LLM model selection)

#### ✅ **core/domain_router.py** — MISSION DOMAIN CLASSIFIER (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION
- **Purpose**: Detect mission domain and return agent profile + context
- **Scope**: Routes **mission goal** → **domain + preferred agents**, not LLM selection
- **Domains**: `software_dev`, `ai_engineer`, `cyber_security`, `automation`, `business`, `saas_builder`, `general`
- **Output**: `{domain, context_prefix, preferred_agents[], max_agents}`
- **Used By**:
  - `core/mission_system.py`
  - `core/orchestrator_lg/langgraph_flow.py`
  - `core/routing/__init__.py` facade
- **Lines**: 128
- **Decision**: ✅ **KEEP** — handles different concern (domain classification, not LLM model selection)

---

### 1.4 Capability Routing (SEPARATE CONCERN — KEEP)

#### ✅ **core/capability_routing/router.py** — CAPABILITY → PROVIDER ROUTER (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION
- **Purpose**: Route goal → capability requirements → best provider (agent/tool/MCP/module)
- **Scope**: TOP-LEVEL orchestration routing, not LLM model selection
- **Key Features**:
  - Resolves capabilities from goal text
  - Scores providers on: reliability, readiness, risk, type preference
  - Enriches with kernel performance data
  - Enriches with domain skill routing
  - Fuzzy capability matching
- **Core Functions**:
  - `route_mission(goal, classification, mode) → RoutingDecision[]`
  - `route_single_capability(capability_id) → RoutingDecision`
- **Used By**:
  - `main.py` registers with `kernel.routing.router`
  - `core/meta_orchestrator.py._route_mission()`
  - `api/routes/capability_routing.py`
  - `kernel/convergence/capability_bridge.py`
- **Lines**: 260
- **Decision**: ✅ **KEEP** — handles different concern (capability abstraction layer)

#### ✅ **kernel/routing/router.py** — KERNEL ROUTING AUTHORITY (PRODUCTION)
- **Status**: ✅ ACTIVE IN PRODUCTION
- **Purpose**: Single kernel entry point for all routing (kernel governance layer)
- **Scope**: AUTHORITY & MONITORING wrapper, delegates to `core/capability_routing/router.py`
- **Design**:
  - Transparent passthrough when core router registered
  - Kernel heuristic fallback when offline
  - Zero imports from core/ (dependency inversion)
- **Core Class**: `KernelCapabilityRouter` with `route()` method
- **Used By**:
  - `core/meta_orchestrator.py` (Phase 0c routing)
  - `kernel/runtime/kernel.py` (kernel authority)
  - Registered at boot: `main.py` → `register_core_router(route_mission)`
- **Lines**: 263
- **Decision**: ✅ **KEEP** — kernel governance layer, not LLM selection

---

## 2. Call Graph: Who Uses Which Router

### 2.1 LLM Model Selection Flow

```
┌─────────────────────────────────────────────────────────────┐
│ LLM MODEL SELECTION (Consolidated Zone)                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  core/llm_routing_policy.py (CANONICAL)                     │
│    ├─ resolve_route(RoutingContext) → model_id             │
│    ├─ classify_dimension(ctx) → RoutingDimension           │
│    ├─ score_model(profile, dimension, ctx) → score         │
│    └─ ModelHealthTracker (static baseline)                 │
│         ▲                                                    │
│         │ ENHANCES VIA MONKEY-PATCH                         │
│         │                                                    │
│  core/adaptive_routing.py (LIVE METRICS)                    │
│    ├─ install_adaptive_routing() (startup)                 │
│    ├─ adaptive_score_model() (replaces score_model)        │
│    ├─ EnhancedHealthTracker (replaces ModelHealthTracker)  │
│    ├─ calibrate_profiles() (sync with metrics_store)       │
│    └─ LiveModelProfile (real perf data)                    │
│                                                               │
│  USAGE:                                                      │
│    - core/routing/__init__.py (unified facade)              │
│    - core/meta_orchestrator.py (via get_enhanced_tracker)   │
│    - Tests: test_llm_routing_policy.py (50+ cases)          │
│    - Tests: test_adaptive_routing.py (15+ cases)            │
│                                                               │
│  DEPRECATED:                                                 │
│  ✗ core/model_router.py (TEST-ONLY, superseded)            │
│     └─ Only used in: test_model_router.py                   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Task/Intent Routing Flow (Separate Layer)

```
┌─────────────────────────────────────────────────────────────┐
│ TASK/INTENT ROUTING (Different Concern)                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  core/task_router.py                                         │
│    ├─ route(user_input, explicit_mode) → RoutingDecision    │
│    │   (mode, agents[], needs_actions, confidence)           │
│    └─ TaskMode: CHAT/RESEARCH/PLAN/CODE/AUTO/NIGHT/IMPROVE  │
│         /BUSINESS                                            │
│                                                               │
│  USED BY:                                                    │
│    ├─ core/jarvis_executor.py (primary entry)               │
│    ├─ core/context_provider.py                              │
│    ├─ business/layer.py                                      │
│    └─ Tests: test_task_router.py, test_orchestrator.py      │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Agent Selection Routing Flow (Separate Layer)

```
┌─────────────────────────────────────────────────────────────┐
│ AGENT SELECTION ROUTING (Different Concern)                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  core/dynamic_agent_router.py (Performance-Based)           │
│    ├─ route_agents(goal, type, complexity, candidates)      │
│    │   → reranked agents[]                                  │
│    ├─ get_agent_specialization_map() (UI diagnostics)       │
│    ├─ get_routing_explanation() (reasoning)                 │
│    └─ detect_multimodal_type(), get_multimodal_agents()     │
│         ▲                                                    │
│         │ CONSUMES DATA FROM                                │
│         ├─ mission_performance_tracker                      │
│         └─ tool_performance_tracker                         │
│                                                               │
│  USED BY:                                                    │
│    ├─ agents/crew.py (agent selection override)             │
│    ├─ core/planner.py (routing explanation)                 │
│    ├─ api/routes/performance.py (diagnostics)               │
│    └─ Tests: test_advanced_capabilities.py                  │
│                                                               │
│  core/domain_router.py (Domain Classification)              │
│    ├─ route(goal) → {domain, context, preferred_agents}     │
│    └─ detect_domain(goal) → domain_name                     │
│                                                               │
│  USED BY:                                                    │
│    ├─ core/mission_system.py                                │
│    ├─ core/orchestrator_lg/langgraph_flow.py               │
│    └─ core/routing/__init__.py                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 Capability Routing Flow (Top-Level Orchestration)

```
┌─────────────────────────────────────────────────────────────┐
│ CAPABILITY ROUTING (Top-Level Orchestration)                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  kernel/routing/router.py (AUTHORITY)                       │
│    └─ KernelCapabilityRouter.route()                        │
│         │                                                    │
│         ├─ DELEGATES TO (via registration)                  │
│         │                                                    │
│         ▼                                                    │
│  core/capability_routing/router.py                          │
│    ├─ route_mission(goal, clf, mode) → RoutingDecision[]    │
│    │   ├─ resolve_capabilities(goal) → requirements[]       │
│    │   ├─ rank_providers(candidates, req) → scored[]        │
│    │   ├─ Enriches with kernel performance                  │
│    │   └─ Enriches with domain skill routing                │
│    └─ route_single_capability(id) → RoutingDecision         │
│                                                               │
│  USED BY:                                                    │
│    ├─ main.py (registers at boot)                           │
│    ├─ core/meta_orchestrator.py._route_mission()            │
│    ├─ kernel/runtime/kernel.py                              │
│    ├─ api/routes/capability_routing.py                      │
│    └─ kernel/convergence/capability_bridge.py               │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Redundancy Analysis

### 3.1 Direct Redundancy: model_router.py vs llm_routing_policy.py

| Feature | model_router.py (Deprecated) | llm_routing_policy.py (Production) |
|---------|-----------------------------|------------------------------------|
| **Routing Approach** | Simple tier mapping (FAST/STANDARD/STRONG) | Multi-dimensional scoring (10 dimensions) |
| **Model Profiles** | None (just tiers) | 8 detailed profiles with cost/latency/quality |
| **Context Awareness** | Task type + complexity | Task description, budget, latency, tokens, vision, local |
| **Scoring** | Basic rules | Composite: quality, cost, latency, health, strength match |
| **Health Tracking** | None | ModelHealthTracker with success rate + recency |
| **Budget Modes** | None | cheap/balanced/premium with weighted scoring |
| **Latency Modes** | None | fast/normal/deep with latency preferences |
| **Production Use** | ❌ Test-only | ✅ Active in production |
| **Lines of Code** | 113 | 596 |

**Verdict**: `model_router.py` is **100% superseded** by `llm_routing_policy.py`. The 16 test cases can be rewritten as integration tests for the canonical router.

---

### 3.2 No Redundancy: Other Routers Serve Different Purposes

| Router | Layer | Concern | Keep? |
|--------|-------|---------|-------|
| `task_router.py` | Intent | User message → TaskMode + agent plan | ✅ YES |
| `dynamic_agent_router.py` | Agent Selection | Mission → best agents (performance data) | ✅ YES |
| `domain_router.py` | Domain | Goal → domain + context | ✅ YES |
| `capability_routing/router.py` | Orchestration | Goal → capabilities → providers | ✅ YES |
| `kernel/routing/router.py` | Governance | Kernel authority + monitoring | ✅ YES |

**These routers do NOT overlap** with LLM model selection. They operate at different abstraction levels:
- **Task routing**: user intent classification
- **Agent routing**: which agents to use
- **Domain routing**: which domain context applies
- **Capability routing**: which provider handles which capability
- **Kernel routing**: governance & authority layer

---

## 4. Proposed Unified Routing Architecture

### 4.1 Canonical LLM Model Selection Router

**Single Source of Truth**: `core/llm_routing_policy.py`

**Enhancement Layer**: `core/adaptive_routing.py` (monkey-patches at startup)

**Facade**: `core/routing/__init__.py` (unified import point)

```python
# Unified LLM routing facade
from core.routing import (
    # Core routing policy
    resolve_route,
    RoutingContext,
    RoutingDecision,
    RoutingDimension,
    BudgetMode,
    LatencyMode,
    
    # Live metrics enhancement
    get_enhanced_tracker,
    calibrate_profiles,
    get_fallback_recommendations,
    install_adaptive_routing,  # Call at startup
)

# Example: Route an LLM request
ctx = RoutingContext(
    role="builder",
    task_description="refactor the authentication module",
    complexity=0.8,
    token_estimate=5000,
    budget=BudgetMode.BALANCED,
    require_code=True,
)
decision = resolve_route(ctx)
# → RoutingDecision(
#     resolved_role="builder",
#     model_id="openai/gpt-5.3-codex",
#     dimension=RoutingDimension.CODE_HEAVY,
#     score=0.89,
#     reason="...",
#   )
```

### 4.2 Strategy Pattern: Pluggable Routing Policies

Current design already implements strategy pattern via:

1. **Dimension Classification**: `classify_dimension(ctx)` — can be overridden
2. **Model Scoring**: `score_model(profile, dimension, ctx)` — can be replaced by `adaptive_score_model()`
3. **Health Tracking**: `ModelHealthTracker` → `EnhancedHealthTracker` (already pluggable via monkey-patch)
4. **Budget/Latency Modes**: Enum-based strategies with weighted scoring

**Extensibility Points**:
```python
# Add new routing dimension
class RoutingDimension(str, Enum):
    # ... existing dimensions
    MEDICAL_REASONING = "medical_reasoning"  # New domain

# Add new model profile
_MODEL_PROFILES["medical_specialist"] = ModelProfile(
    model_id="medical/med-llm-v2",
    settings_attr="openrouter_medical_model",
    quality=0.95, cost=0.80, latency=0.60,
    context_window=200_000,
    strengths={RoutingDimension.MEDICAL_REASONING},
    cost_tier="premium",
)

# Add new budget mode weights
_BUDGET_WEIGHTS[BudgetMode.ULTRA_CHEAP] = {
    "quality": 0.05, "cost": 0.70, "latency": 0.05,
    "health": 0.10, "strength": 0.10,
}
```

### 4.3 Integration Points

**Current Integration** (no changes needed):
- `core/meta_orchestrator.py` already uses `get_enhanced_tracker()` for telemetry
- `core/routing/__init__.py` already exports unified interface
- `adaptive_routing.py` already installs at startup via `core/routing/__init__.py`

**Future Integration** (optional enhancements):
- Kernel performance data already enriches capability routing via `kernel/convergence/performance_routing.py`
- Could extend to enrich LLM routing: kernel tracks per-model latency/cost → feeds into adaptive_routing

---

## 5. Migration Plan

### Phase 1: Deprecate model_router.py ✅ COMPLETE

**Already Done**:
- Header comment marks it as "DEPRECATED: This router is NOT used in production"
- No production imports found (only test usage)

**Remaining**:
1. Migrate 16 test cases from `test_model_router.py` to `test_llm_routing_policy.py` as integration tests
2. Add deprecation warnings if any code tries to import
3. Move file to `deprecated/model_router.py` after test migration

### Phase 2: Document Canonical Router ✅ RECOMMENDED

1. Add comprehensive docstring examples to `llm_routing_policy.py`
2. Create `docs/LLM_ROUTING_GUIDE.md` with:
   - When to use which budget/latency mode
   - How to add new models
   - How to extend dimensions
   - Troubleshooting routing decisions
3. Update `ARCHITECTURE.md` to clarify routing layers

### Phase 3: Enhance Observability (Optional)

1. Add routing decision explanations to UI
2. Export routing metrics to Prometheus/Grafana
3. Add alerting on routing failures
4. Dashboard for per-model cost/latency trends

---

## 6. Files to Keep vs Deprecate

### ✅ KEEP (Production Active)

| File | Purpose | Reason |
|------|---------|--------|
| `core/llm_routing_policy.py` | **CANONICAL LLM ROUTER** | Production model selection |
| `core/adaptive_routing.py` | Live metrics enhancement | Enhances canonical router with real data |
| `core/task_router.py` | User intent classification | Different concern (intent → agents) |
| `core/dynamic_agent_router.py` | Agent performance routing | Different concern (agents selection) |
| `core/domain_router.py` | Domain classification | Different concern (domain context) |
| `core/capability_routing/router.py` | Capability orchestration | Different concern (top-level routing) |
| `kernel/routing/router.py` | Kernel authority | Governance layer |
| `core/routing/__init__.py` | Unified facade | Central import point |

### ⚠️ DEPRECATE (Superseded)

| File | Status | Migration Path |
|------|--------|----------------|
| `core/model_router.py` | TEST-ONLY | Move to `deprecated/`, migrate tests to `test_llm_routing_policy.py` |

### 🔍 SKILL ROUTERS (Out of Scope)

These are domain-specific skill matchers, not LLM routers:
- `core/skills/domain_skill_router.py` (abstract base)
- `core/skills/security_skill_router.py` (security domain skills)

---

## 7. Recommended Actions

### Immediate (Priority 1)
1. ✅ **Mark model_router.py for removal** — add loud deprecation warning
2. ✅ **Migrate test_model_router.py** — rewrite as integration tests for llm_routing_policy
3. ✅ **Update imports** — ensure no new code imports model_router

### Short-Term (Priority 2)
4. 📖 **Document canonical router** — add examples, troubleshooting guide
5. 📊 **Add routing telemetry** — track routing decisions in metrics_store
6. 🧪 **Test adaptive routing coverage** — ensure all code paths tested with live data

### Long-Term (Priority 3)
7. 🔗 **Integrate kernel performance** — feed kernel model perf data into adaptive_routing
8. 🎨 **UI routing dashboard** — visualize routing decisions and model health
9. 🚀 **Auto-tune routing** — use historical data to adjust weights

---

## 8. Success Metrics

**Consolidation Success**:
- ✅ Single import point for LLM routing: `from core.routing import resolve_route`
- ✅ Zero production imports of `model_router.py`
- ✅ All routing tests use canonical router
- ✅ Routing decisions observable in metrics_store

**Performance Goals**:
- 🎯 Routing latency < 10ms (current: ~5ms for cached)
- 🎯 Adaptive routing blend factor > 0.5 after 100 calls
- 🎯 Cost savings > 30% vs always using premium models

---

## 9. Architectural Principles

### Separation of Concerns ✅
- **Task routing** (intent) ≠ **Agent routing** (who) ≠ **LLM routing** (which model) ≠ **Capability routing** (what)
- Each router operates at different abstraction level
- No cross-dependencies between routing layers

### Single Responsibility ✅
- `llm_routing_policy.py`: static model profiles & scoring
- `adaptive_routing.py`: live metrics enhancement
- `task_router.py`: intent classification
- `dynamic_agent_router.py`: agent performance selection
- `capability_routing/router.py`: capability → provider mapping

### Strategy Pattern ✅
- Routing dimensions = strategies for model selection
- Budget/latency modes = weighted scoring strategies
- Health tracking = pluggable via monkey-patch
- Scoring function = replaceable (static → adaptive)

### Fail-Open Design ✅
- All routers degrade gracefully
- adaptive_routing installs via monkey-patch (can be disabled)
- kernel routing has heuristic fallback
- No hard dependencies between layers

---

## 10. Conclusion

**Redundancy Found**: Only `model_router.py` is truly redundant (test-only stub superseded by production router).

**Recommendation**: 
- ✅ **DEPRECATE**: `core/model_router.py`
- ✅ **KEEP**: All other routers (different concerns, active in production)
- ✅ **CANONICAL**: `core/llm_routing_policy.py` + `core/adaptive_routing.py`
- ✅ **FACADE**: `core/routing/__init__.py` (single import point)

**No major refactoring needed** — architecture is already well-separated. Just deprecate the legacy test stub and document the canonical router.

---

## Appendix A: File Locations

```
/root/Jarvismax-master/
├── core/
│   ├── llm_routing_policy.py          # ✅ CANONICAL LLM ROUTER (596 lines)
│   ├── adaptive_routing.py             # ✅ LIVE METRICS ENHANCEMENT (588 lines)
│   ├── model_router.py                 # ⚠️ DEPRECATED TEST STUB (113 lines)
│   ├── task_router.py                  # ✅ INTENT CLASSIFIER (360 lines)
│   ├── dynamic_agent_router.py         # ✅ AGENT PERFORMANCE ROUTER (430 lines)
│   ├── domain_router.py                # ✅ DOMAIN CLASSIFIER (128 lines)
│   ├── routing/
│   │   └── __init__.py                 # ✅ UNIFIED FACADE
│   ├── capability_routing/
│   │   └── router.py                   # ✅ CAPABILITY ORCHESTRATION (260 lines)
│   └── skills/
│       ├── domain_skill_router.py      # 🔍 SKILL MATCHER (not LLM routing)
│       └── security_skill_router.py    # 🔍 SECURITY SKILLS (not LLM routing)
└── kernel/
    └── routing/
        └── router.py                    # ✅ KERNEL AUTHORITY (263 lines)
```

## Appendix B: Test Coverage

| Router | Test File | Test Count | Status |
|--------|-----------|------------|--------|
| llm_routing_policy.py | test_llm_routing_policy.py | 50+ | ✅ Comprehensive |
| adaptive_routing.py | test_adaptive_routing.py | 15+ | ✅ Good |
| model_router.py | test_model_router.py | 16 | ⚠️ Migrate to canonical |
| task_router.py | test_task_router.py, test_task_router_edge.py | 20+ | ✅ Good |
| dynamic_agent_router.py | test_advanced_capabilities.py | 6+ | ✅ Good |
| domain_router.py | test_domain_routing_integration.py | 10+ | ✅ Good |
| capability_routing/router.py | test_capability_routing.py | 30+ | ✅ Comprehensive |
| kernel/routing/router.py | test_kernel_routing.py | 5+ | ✅ Good |

---

**Document Version**: 1.0  
**Date**: 2026-04-11  
**Author**: Hermes Agent (Consolidation Audit)
