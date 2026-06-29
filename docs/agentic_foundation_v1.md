# Béa Agentic Foundation v1
# Architecture summary — branch feat/agentic-foundation-v1

## Overview

Béa v1 Agentic Foundation transforms Béa into a controlled agentic platform
inspired by SWE-agent, MetaGPT, MemGPT, AutoPR, GPT-Researcher, Vanna/Wren.

All capabilities are **deny-by-default**, **audited via structlog**, and
require **human approval** for any action with side effects.

---

## Packages

### `agent_runtime/` — Agent Computer Interface (SWE-agent)

| File | Role |
|------|------|
| `actions.py` | ActionType enum, ActionRequest, ActionResult (Pydantic v2) |
| `policy.py` | RiskLevel, CommandPolicy, SandboxPolicy, ACTION_RISK |
| `registry.py` | ACIActionRegistry — deny-by-default, capability checks |
| `executor.py` | ACIExecutor — 5-step enforcement chain |
| `sandbox.py` | SandboxWrapper — wraps DockerSandbox, fallback subprocess |
| `results.py` | not_implemented_handler stub |

**Key invariant:** Every agent action goes through `ACIExecutor.execute()`.
Unknown actions → `blocked`. Missing capability → `blocked`. Sensitive path → `blocked`.
High risk → `approval_required`. Only then: handler called.

### `agent_workflows/` — SOP Multi-Agent Workflows (MetaGPT)

| File | Role |
|------|------|
| `verdicts.py` | ReviewVerdict (P0/P1/P2/P3), WorkflowVerdict |
| `roles.py` | AgentRole enum, AgentProfile with capabilities |
| `engine.py` | SOPWorkflowEngine — async step runner |
| `configs/agents.yaml` | Default agent profiles |
| `configs/workflows.yaml` | 4 standard SOP workflows |

**Key invariant:** P0 verdicts stop the workflow immediately.
P1 verdicts mark workflow failed but allow remaining steps.

### `agent_memory/` — Structured Memory (MemGPT)

| File | Role |
|------|------|
| `models.py` | MemoryType, StructuredMemory (realm+source+confidence required) |
| `store.py` | AgentMemoryStore — recall, supersede, context_for_agent |
| `codebase.py` | CodebaseMemoryService — AST scan + repo_map wrap |
| `learning.py` | learn_from_failure/success, LessonMemory bridge |

**Key invariant:** Every memory entry requires `realm`, `source`, and `confidence`.
No unsourced claims. Low-confidence memories flagged `[UNCERTAIN]`.

### `agent_github/` — GitHub Mission Loop (AutoPR/Sweep)

| File | Role |
|------|------|
| `labels.py` | BEA_LABELS — 15 canonical labels (P0-P3, agentic, etc.) |
| `issues.py` | IssueClassifier — deterministic keyword+label classifier |
| `mission_loop.py` | GitHubMissionLoop — plan → PR draft, never auto-merge |

**Key invariant:** PR drafts always `pr_draft=True`. Security and self-improvement
issues → `HUMAN_REVIEW` status. Branch: `bea/issue-<N>/<kind>`.

### `agent_research/` — Research Agent (GPT-Researcher)

| File | Role |
|------|------|
| `sources.py` | ResearchSource — social media blocked, cookie-gated flagged |
| `reports.py` | ResearchReport — sources mandatory, no personal data |
| `agent.py` | ResearchAgent — SourcePolicy + build_report() |

**Key invariant:** Every ReportSection must reference at least one source URL.
`contains_personal_data=True` always rejected.

### `agent_data/` — Data Agent (Vanna/Wren)

| File | Role |
|------|------|
| `sql_policy.py` | check_sql_safety — SELECT only, LIMIT capped at MAX_ROWS=1000 |
| `reports.py` | DataQueryReport — full audit trail |
| `agent.py` | DataAgent — explain→approve→execute pipeline |

**Key invariant:** `approved_by` required on every `execute()` call.
Only SELECT queries execute. LIMIT always injected/capped.

### `agent_self_improvement/` — Controlled Self-Improvement (MemGPT/Voyager)

| File | Role |
|------|------|
| `skill_library.py` | Skill (test_code + source_ref required), SkillLibrary |
| `improvement_issues.py` | ImprovementIssue — creates GitHub issue, never direct patch |
| `reflection.py` | ReflectionAgent — failure detection → ImprovementIssue |

**Key invariant:** `creates_direct_patch=False` always enforced.
SECURITY kind: `human_approval_required=True` always.
Max 1 issue per reflection cycle (gate cap).

---

## Security Model

See `docs/agentic_security_model.md`

## Test Summary

| Package | Tests | Status |
|---------|-------|--------|
| agent_runtime | 8 | PASS |
| agent_workflows | 15 | PASS |
| agent_memory | 26 | PASS |
| agent_github | 24 | PASS |
| agent_research | 23 | PASS |
| agent_data | 23 | PASS |
| agent_self_improvement | 23 | PASS |
| **Total** | **142** | **PASS** |

---

## Absolute Constraints (Always Enforced)

1. Never modify main directly.
2. All new capabilities deny-by-default.
3. No execution on host (ACI sandbox for all commands).
4. No secret reading by agents (env filter in SandboxWrapper).
5. No business/financial/cyber action without human approval.
6. Cyber actions defensive only, scope-bound.
7. Self-improvement via GitHub issues, never direct patches.
8. PR drafts never auto-merged.
9. Every new feature: tests + structlog audit + docs.
