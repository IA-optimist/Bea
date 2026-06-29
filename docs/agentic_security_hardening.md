# Agentic Security Hardening

This document records the security posture of the current agentic foundation.
It is a hardening baseline, not a claim that all historical Bea runtime paths
are fully migrated behind the new ACI.

## Enforced Now

- Deny-by-default action registry.
- Unknown actions blocked.
- Missing capability blocked.
- Realm checks supported through `CommandPolicy.allowed_realms`.
- Path scope checks use resolved paths rather than string prefix matching.
- Risk threshold produces `approval_required`.
- Sensitive paths require explicit allow.
- Secret-like values are redacted in action output, errors, payload summaries,
  and stored memory content.
- Sandbox wrapper rejects shell metacharacters and does not use `shell=True`.
- Sandbox wrapper uses command allowlist, sanitized environment, and timeout.
- GitHub mission loop creates draft PR material only; no auto-merge path exists.
- Review gate blocks P0/P1 findings.
- Review gate blocks sensitive auth/sandbox/tool/approval/memory changes unless
  a `SecurityAgent` reviewer is present.
- Self-improvement creates issues/proposals and learning memories; it does not
  directly patch code.
- Data agent remains SELECT-only according to existing data-agent tests.

## Tests Added In This Hardening Pass

- Runtime validation and policy tests in `tests/agent_runtime/test_agentic_hardening.py`.
- End-to-end agentic integration tests in
  `tests/agent_runtime/test_agentic_integration.py`.

## Security-Relevant Gaps

- Legacy execution paths in `core/` and `scripts/` are documented in
  `docs/execution_surface.md` but are not all routed through `ACIExecutor`.
- `apply_patch_handler` is deliberately small and should not be treated as a
  full replacement for mature patch tooling yet.
- Network allowlist enforcement is modeled in policy but not broadly integrated
  across all historical tools.
- GitHub API mutation code is not wired here; this pass hardens mission loop
  planning/body generation and safety invariants.

## Required Rule For Future Agentic Changes

Any change touching auth, sandboxing, tool execution, memory, approvals,
policy, or GitHub write behavior must include dedicated tests for the new risk.
