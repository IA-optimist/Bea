# Agentic Security Model — Béa v1

## Threat Model

Agents are untrusted until explicitly granted capabilities.
The attack surface is: prompt injection → unauthorized action.

### Defenses

| Threat | Defense |
|--------|---------|
| Prompt injection via payload | `is_sensitive_path()` blocks kernel paths |
| Command injection via payload | `_COMMAND_METACHARS` rejected in SandboxWrapper |
| Secret exfiltration | Env sanitized in sandbox (KEY/TOKEN/SECRET/PASS/AUTH filtered) |
| Sensitive path access | `SENSITIVE_PATH_PREFIXES` in `agent_runtime/policy.py` |
| DML injection via data agent | `check_sql_safety()` SELECT-only + comment blocking |
| Social media in research | `is_social_media_url()` rejects Twitter/X/Reddit/etc. |
| Direct self-patching | `creates_direct_patch=False` enforced in `ImprovementIssue` |
| Security bypass | SECURITY kind always `human_approval_required=True` |
| Auto-merge of PRs | `pr_draft=True` always, never auto-merge invariant |
| Log leakage of secrets | `core/observability/redactor.py` redacts 40+ char tokens |

## Capability Model

| Role | Capabilities |
|------|-------------|
| Planner | read, write |
| Coder | read, write, execute, sandbox |
| Reviewer | read, execute |
| Tester | read, execute, sandbox |
| Researcher | read |
| Analyst | read |
| Gatekeeper (human) | ∅ (humans don't get capabilities — they approve) |

## Risk Levels

| Level | Actions | Auto-approve? |
|-------|---------|---------------|
| SAFE | read_file, list_files, search | Yes |
| LOW | write_report, run_linter, run_typecheck | Yes |
| MEDIUM | run_tests, create_branch | Warn + log |
| HIGH | apply_patch, create_pr_draft | Approval required |
| CRITICAL | (none registered) | Always blocked |

## Protected Paths

See `agent_runtime/policy.py:SENSITIVE_PATH_PREFIXES` and
`core/self_improvement/protected_paths.py`.

Core protected areas:
- `.env` files (secrets)
- `secrets/` directory
- `core/security/`
- `core/tool_executor.py`
- `core/meta_orchestrator.py`
- `kernel/improvement/`
- `api/_deps/`

## Audit Trail

Every ACI action is logged by `ACIExecutor` via structlog:
- `aci_action_unknown` — deny-by-default triggered
- `aci_action_denied_by_policy` — CommandPolicy blocked
- `aci_capability_missing` — agent lacks required capability
- `aci_sensitive_path_blocked` — path guard triggered
- `aci_approval_required` — risk threshold exceeded
- `aci_action_executed` — action completed (status + duration)

Data agent queries are logged:
- `data_agent_execute` — with query preview + approved_by

Research source rejections are logged:
- `research_source_rejected` — with URL + reason

Self-improvement issues are logged:
- `reflection_issue_created` — with kind + failure_count
- `skill_registered` / `skill_deprecated` / `skill_human_verified`

## Human Gates

| Trigger | Gate |
|---------|------|
| ANY action risk > policy threshold | `approval_required` returned |
| SECURITY improvement issue | `human_approval_required=True` |
| Self-improvement SECURITY kind | ImprovementIssue validator blocks |
| GitHub PR draft | Never auto-merged (pr_draft=True invariant) |
| Data agent query | `approved_by` field required |
| Kernel improvement | `kernel/improvement/gate.py` gate consulted |
