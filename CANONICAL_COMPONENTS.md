# JarvisMax Canonical Components Registry

This document identifies the authoritative implementation for each core system component where multiple versions exist.

**Last Updated:** 2026-04-07 13:35 UTC  
**Audit Phase:** P0 Complete

---

## Mission Storage

### CANONICAL: `api/mission_store.py` (MissionStateStore)
- **Lines:** 169
- **Class:** MissionStateStore
- **Rationale:** Actively used by all API routes (mission_control.py, missions.py, monitoring.py). Singleton pattern with event streaming. Integrated with failure collection and self-improvement V3.
- **Imports:** 
  - api/routes/mission_control.py
  - api/routes/missions.py
  - api/routes/monitoring.py
  - api/event_emitter.py
  - core/self_improvement/failure_collector.py

### LEGACY (moved to core/_legacy/)
- `core/mission_persistence.py` (MissionPersistenceStore) - 342 lines, older persistence layer
- Note: `core/canonical_mission_store.py` (270 lines) still active but only used by orchestration_bridge

---

## Policy Engine

### CANONICAL: `kernel/policy/engine.py` (KernelPolicyEngine)
- **Lines:** ~250
- **Class:** KernelPolicyEngine, RiskEngine, ApprovalGate
- **Rationale:** Imported by kernel/runtime/boot.py as the primary policy enforcement mechanism. Part of kernel architecture layer. Handles risk assessment and approval workflows.
- **Imports:**
  - kernel/runtime/boot.py
  - kernel/adapters/policy_adapter.py (evaluate_action)
  - kernel/convergence/policy_bridge.py

### LEGACY (moved to core/_legacy/)
- `core/policy/policy_engine.py` (PolicyEngine) - 189 lines, older rule-based system
- Note: `core/policy_engine_LEGACY_20260407.py` already marked as legacy

---

## Orchestrator

### CANONICAL: `core/meta_orchestrator.py` (MetaOrchestrator)
- **Lines:** ~600
- **Class:** MetaOrchestrator
- **Rationale:** Top-level orchestration layer. Imported by api/routes/convergence.py and api/routes/mission_persistence.py. Coordinates multi-agent workflows and capability routing. Interfaces with kernel through orchestration_bridge.
- **Imports:**
  - api/routes/convergence.py (get_meta_orchestrator)
  - api/routes/mission_persistence.py (get_orchestrator)
  - core/orchestration_bridge.py

### Secondary (Active)
- `business/business_orchestrator.py` - Domain-specific orchestrator for business agents
- `core/capability_routing/router.py` - Capability-based routing system

### LEGACY (moved to core/_legacy/)
- `core/orchestrator_v2.py` (OrchestratorV2) - 456 lines, previous generation
- Note: `core/orchestrator_LEGACY_20260407.py` already marked as legacy

---

## Self-Improvement Loop

### CANONICAL: `core/self_improvement/` (V3 Package)
- **Structure:** 30+ modular components
- **Main Entry:** improvement_loop.py, engine.py
- **Rationale:** Most recent implementation (V3). Fully modularized architecture with separated concerns:
  - Failure collection & analysis
  - Candidate generation & scoring
  - Safe execution & validation
  - Git integration & deployment gates
  - Human approval workflows
- **Key Modules:**
  - `engine.py` - Main coordination
  - `improvement_loop.py` - Loop orchestration
  - `failure_collector.py` - Integrates with MissionStateStore
  - `validation_runner.py` - Test execution
  - `promotion_pipeline.py` - Deployment workflow
  - `sandbox_executor.py` - Safe code execution

### LEGACY (moved to core/_legacy/)
- `core/self_improvement.py` - 15KB monolithic V1
- `core/self_improvement_engine.py` - 22KB V2 engine
- `core/self_improvement_loop.py` - 45KB V2 loop

---

## Domain Configuration

### Production Domain
- **URL:** https://jarvis.jarvismaxapp.co.uk
- **Status:** Active (HTTP 200 on /health endpoint verified 2026-04-07)
- **Configuration:**
  - `.env`: DOMAIN=jarvis.jarvismaxapp.co.uk, BASE_URL=https://jarvis.jarvismaxapp.co.uk
  - Reverse proxy: Caddy (see Caddyfile)

### DNS & TLS
- Managed through Caddy automatic HTTPS
- Health check endpoint: /health
- API base: /api/v1

---

## API Routes Architecture

### Router Count: 55+ declared routers
### Active Routers (mounted in main.py)
- /api/v1/missions (missions.py)
- /api/v1/mission-control (mission_control.py) 
- /api/v1/monitoring (monitoring.py)
- /api/v1/convergence (convergence.py)
- /api/v1/mission-persistence (mission_persistence.py)
- Additional business/agent-specific routes

See API_CLEANUP.md for full router audit.

---

## Cross-References

### Core Dependencies
- MissionStateStore ← failure_collector ← self_improvement/engine
- KernelPolicyEngine ← runtime/boot ← kernel initialization
- MetaOrchestrator ← api/routes ← HTTP endpoints

### Kernel Integration Points
- `kernel/runtime/boot.py` - System initialization, policy loading
- `kernel/adapters/policy_adapter.py` - Core-to-kernel policy bridge
- `kernel/convergence/policy_bridge.py` - Convergence layer policy evaluation

---

## Migration Notes

All legacy components moved to `core/_legacy/` directory with README documentation.
No active imports should reference legacy paths.

### Verification Commands
```bash
# Check for legacy imports
grep -r "from core.mission_persistence import" . --include="*.py"
grep -r "from core.orchestrator_v2 import" . --include="*.py"
grep -r "from core.self_improvement import" . --include="*.py"

# Verify canonical imports work
python -c "from api.mission_store import MissionStateStore; print('OK')"
python -c "from kernel.policy.engine import KernelPolicyEngine; print('OK')"
python -c "from core.meta_orchestrator import MetaOrchestrator; print('OK')"
```

---

## Next Steps (P1 Phase)

1. Core/ factorization - reduce bloat, extract tools
2. Auth consolidation - unify JWT/API key/session auth
3. Dead route removal - move unused routers to api/_unused/
4. Bare except cleanup - add proper exception handling
5. Import validation - ensure no broken references

---

*Document maintained as part of JarvisMax technical debt resolution initiative.*
