# Agentic Beta Readiness

## Verdict

Agentic foundation: partially ready for supervised technical private beta.

It is not ready for unsupervised public beta. The new runtime/security layer is
meaningfully hardened, but several historical execution paths still exist
outside the new ACI and must remain human-gated or experimental.

## Ready

- Structured `ActionRequest` and `ActionResult`.
- Deny-by-default action registry.
- Capability and realm checks.
- Resolved path scoping for write actions.
- Minimal safe `apply_patch` handler with diff summary and hashes.
- Redacted audit payload summaries.
- Memory schema with source, realm, confidence, expiry, delete, and redaction.
- Codebase memory v1 for Python symbols/imports/search/impact/test hints.
- Machine-readable review gate.
- GitHub PR body generation that requires tests and a review verdict.
- Self-improvement loop that creates learning memory and issues, not patches.

## Partially Ready

- Sandbox execution: hardened ACI wrapper exists, but historical subprocess
  surfaces still need migration or policy adapters.
- Data agent: read-only SQL behavior is covered by existing tests, but broader
  database connection hardening must be reviewed per deployment.
- Research agent: sourced-report validation exists, but live browsing behavior
  must remain constrained by source and network policy.
- GitHub loop: safe planning/body logic exists, but actual GitHub mutation
  calls need token/permission tests before autonomous use.

## Not Ready

- Public beta.
- Fully unsupervised agentic code modification.
- Auto-merge.
- Offensive cyber or bug bounty execution without explicit written scope.
- Business automation, deployment automation, or financial actions without
  human approval.

## Remaining Risks

- Legacy `core/` subprocess paths are not all behind `ACIExecutor`.
- Network policy is not globally enforced across every old tool.
- `apply_patch_handler` supports only a minimal update patch format.
- Full `pytest -q` did not complete within 300 seconds in the local validation
  environment for this pass. Targeted agentic tests and `validate_local --quick`
  passed, but full-suite runtime must still be investigated before broader
  release.

## Validation Evidence For This Pass

| Command | Result |
| --- | --- |
| `pytest tests/agent_runtime/test_agentic_hardening.py tests/agent_runtime/test_agentic_integration.py -q` | PASS, 13 passed |
| `pytest tests/agent_runtime tests/agent_memory tests/agent_workflows tests/agent_github tests/agent_research tests/agent_data tests/agent_self_improvement -q` | PASS, 155 passed |
| `ruff check agent_runtime agent_memory agent_workflows agent_github tests/agent_runtime` | PASS |
| `python scripts/validate_local.py --quick` | PASS |
| `pytest -q` | TIMEOUT after 300 seconds, no failure output captured |

## Recommended Next PRs

1. Route legacy tool execution through `ACIExecutor` or a compatibility adapter.
2. Expand `apply_patch_handler` or delegate to a mature patch engine with the
   same path and audit guards.
3. Add tokenless and token-present GitHub API tests for PR draft creation.
4. Add deployment-specific database read-only connection tests.
5. Add network policy enforcement tests for research and sandboxed actions.
