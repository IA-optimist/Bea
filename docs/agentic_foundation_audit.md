# Agentic Foundation Audit
# Gap Analysis: Béa vs SWE-agent / MetaGPT / MemGPT targets
# Generated: 2026-06-28 on branch feat/agentic-foundation-v1

PUBLIC_BETA_READY: false
DOCS_TRUTH_SYNC: true

---

## 1. Important Files Found

### Core Runtime
| File | Role |
|------|------|
| `core/actions/action_model.py` | CanonicalAction, ActionStatus — action lifecycle model |
| `core/tool_executor.py` | ToolExecutor — L4 tools (file, git, docker, web, test) |
| `core/tool_permissions.py` | ToolPermission — risk_level, requires_approval per tool |
| `core/execution/policy.py` | PolicyViolation, blocked patterns — execution safety |
| `core/policy/control_profiles.py` | Control profiles for execution modes |
| `executor/desktop_env/sandbox.py` | DockerSandbox — true Docker isolation, copy-on-write, --network none |
| `core/self_improvement/sandbox_executor.py` | In-process sandbox with ALLOWED_COMMANDS whitelist |
| `kernel/improvement/gate.py` | Kernel gate: MAX_PER_RUN=1, COOLDOWN_HOURS=24, MAX_FAILURES=3 |

### Memory
| File | Role |
|------|------|
| `core/memory/memory_item.py` | MemoryItem, MemoryItemType, MemoryItemStatus |
| `core/memory/operational_memory.py` | OperationalMemoryStore (SQLite) |
| `core/memory/vector_memory.py` | VectorMemoryStore (Qdrant) |
| `core/memory/episodic_store.py` | Episodic memory store |
| `core/memory/memory_layers.py` | Memory layer abstraction |

### Code Intelligence
| File | Role |
|------|------|
| `core/coding_agent/repo_map.py` | build_repo_map — AST-based repo map with symbol ranking |
| `core/repo_map/repo_map_service.py` | RepoMapService — high-level API |
| `core/coding_agent/artifact_validator.py` | validate_coding_report, _has_syntax_validation |
| `core/coding_agent/quality_gate.py` | Quality gate for artifacts |

### Agents
| File | Role |
|------|------|
| `agents/registry.py` | AGENT_CLASSES — all registered agents |
| `agents/crew.py` | Atlas, Scout, Forge, Lens, Vault, Shadow, Pulse, Night agents |
| `agents/contracts.py` | Agent contracts / interfaces |
| `core/skills/skill_models.py` | SkillModel, skill registry |
| `core/skills/skill_registry.py` | SkillRegistry |

### Self-improvement
| File | Role |
|------|------|
| `core/self_improvement/safety_boundary.py` | PROTECTED_RUNTIME, SafetyBoundary |
| `core/self_improvement/protected_paths.py` | PROTECTED_FILES, PROTECTED_DIRS, PROTECTED_PATTERNS |
| `core/self_improvement/human_gate.py` | Human approval gate |
| `core/self_improvement/lesson_memory.py` | Lesson memory from failures |
| `core/self_improvement/improvement_loop.py` | Improvement loop v3 hardened |
| `core/self_improvement/git_agent.py` | Git operations for self-improvement |

### Security
| File | Role |
|------|------|
| `core/security/rbac.py` | Role-based access control |
| `core/security/input_sanitizer.py` | Input sanitization, anti-injection |
| `core/security/secret_audit.py` | Secret detection and audit |
| `core/security/code_guard.py` | Code execution guard |
| `core/observability/redactor.py` | Log redaction (API keys 40+ chars) |

### Workflow
| File | Role |
|------|------|
| `core/workflow/workflow_engine.py` | WorkflowEngine — existing workflow system |
| `core/workflow/scheduler.py` | Task scheduler |
| `core/workflow/executor.py` | Workflow executor |

---

## 2. Modules to Reuse (Do NOT Duplicate)

- `executor/desktop_env/sandbox.py` → wrap in `agent_runtime/sandbox.py`
- `core/tool_permissions.py` → reference in `agent_runtime/policy.py`
- `core/actions/action_model.py` → extend, do NOT replace
- `core/self_improvement/protected_paths.py` → import in ACI path guard
- `core/self_improvement/safety_boundary.py` → import in ACI policy
- `core/security/input_sanitizer.py` → use in ACI for payload sanitization
- `core/observability/redactor.py` → use in all ACI logs
- `core/memory/operational_memory.py` → backend for `agent_memory/store.py`
- `core/coding_agent/repo_map.py` → use in `agent_memory/codebase.py`
- `kernel/improvement/gate.py` → enforce in `agent_self_improvement/`
- `core/self_improvement/lesson_memory.py` → use in `agent_memory/learning.py`
- `core/skills/skill_registry.py` → extend, do NOT replace in `agent_self_improvement/skill_library.py`

---

## 3. Modules NOT to Break

| Module | Why critical |
|--------|-------------|
| `core/meta_orchestrator.py` | Main mission orchestrator |
| `core/tool_executor.py` | All L4 tool calls |
| `api/main.py` + `api/routes/` | 539+ routes, public API |
| `kernel/improvement/gate.py` | Safety invariant |
| `core/self_improvement/protected_paths.py` | Security boundary |
| `core/security/startup_guard.py` | Boot-time safety |
| `core/policy_engine.py` | Policy enforcement |
| `core/memory/operational_memory.py` | Prod SQLite store |
| `executor/desktop_env/sandbox.py` | True isolation |
| `core/coding_agent/artifact_validator.py` | Completion truth gate |

---

## 4. Current Gaps vs Target

| Target capability | Gap | Priority |
|-------------------|-----|----------|
| ACI typed interface (SWE-agent style) | `core/actions/action_model.py` exists but no ACIExecutor enforcing deny-by-default per action | P0 |
| Action capability registry | No central registry mapping ActionType→CapabilityRequired+RiskLevel | P0 |
| Structured SOP verdicts (MetaGPT) | `core/workflow/workflow_engine.py` exists but no ReviewVerdict model, no P0/P1 auto-block | P1 |
| Multi-agent SOP configs (YAML) | No `configs/agents.yaml` or `configs/workflows.yaml` | P1 |
| Typed multi-memory (MemGPT) | Memory exists but no MemoryType/realm/source/confidence constraints at Pydantic level | P1 |
| Codebase memory v1 | `repo_map.py` exists but no CodebaseMemoryService wrapper with stable interface | P2 |
| GitHub Mission Loop (AutoPR/Sweep) | No `agent_github/` — issues not wired to mission creation | P1 |
| Research Agent structured reports | `web_scout.py` exists but no ResearchReport Pydantic model requiring sources | P2 |
| Data Agent SQL read-only | No DataAgent, no check_sql_safety, no explain-before-execute | P2 |
| Self-improvement via GitHub issues | `improvement_loop.py` can patch directly — no forced GitHub issue step | P1 |
| Beta gates checklist | `docs/beta_gates.md` missing | P1 |

---

## 5. Implementation Plan (Small Commits)

```
Phase 0: docs(audit): agentic foundation audit — gap analysis vs SWE-agent/MetaGPT targets
Phase 1: feat(aci): Agent Computer Interface — deny-by-default action layer
Phase 2: feat(sop): SOP multi-agent workflow layer — MetaGPT-inspired verdicts
Phase 3: feat(memory): structured agent memory with realm/source/confidence constraints
Phase 4: feat(github): GitHub Mission Loop — issue→plan→branch→PR draft, never auto-merge
Phase 5: feat(research): Research Agent — sourced-only reports, no personal data
Phase 6: feat(data): Data Agent — SQL read-only with explain-before-execute
Phase 7: feat(self-improvement): controlled self-improvement via issues, never direct patches
Phase 8: docs(agentic): security model, memory model, github loop, beta gates checklist
Phase 9: chore(agentic): phase 9 — quality gate, test summary, final status
```

Each phase adds tests + logs. No phase breaks existing API.
New capabilities are opt-in, deny-by-default.
