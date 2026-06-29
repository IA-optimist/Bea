# Agentic Test Matrix

This matrix is the required coverage map for the agentic foundation. It is not
a marketing checklist. A row is only marked covered when a local unit or
integration test exists in the repository.

## Runtime

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Unknown action | Blocked by deny-by-default registry | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Action without capability | Blocked before handler execution | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Action outside realm | Blocked by `CommandPolicy.allowed_realms` | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Action outside path | Blocked by resolved path scope | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Risky action | Requires approval above configured risk | Existing runtime policy tests plus hardened gate | Partial |
| Action blocked by policy | Returns structured `blocked` result | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Secret redaction | Payload/output/error redacted | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Timeout | Sandbox wrapper has timeout | Existing sandbox tests | Partial |
| Max output | `ActionResult` bounds large text output | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Network denied | `SandboxPolicy.network` defaults to `none` | Existing sandbox policy | Partial |

## Workflow

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Code mission with tests OK | Reviewer can approve and PR body can be drafted | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| Code mission without tests | `needs_changes` minimum | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Sensitive code mission without SecurityAgent | `block` | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| P0/P1 verdict | `block` | `agent_workflows/review_gate.py` tests | Covered |
| P2/P3 verdict | Allowed according to policy if tests/security pass | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| Reviewer absent | `block` | `agent_workflows/review_gate.py` tests | Covered |
| Invalid workflow config | Existing workflow engine validation | Existing workflow tests | Partial |

## Memory

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Source mandatory | Pydantic validation rejects missing source | Existing memory tests | Covered |
| Realm mandatory | Pydantic validation rejects missing realm | Existing memory tests | Covered |
| Confidence mandatory and bounded | Pydantic validation enforces 0.0-1.0 | Existing memory tests | Covered |
| Recall filtered by realm | Cross-realm recall is not returned | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Expired memory excluded | `expires_at` excluded from recall/get | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Sensitive memory redacted | Secret-like content redacted before storage | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Delete/forget | `AgentMemoryStore.delete` removes record | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Learning memory from failure | Failure creates LESSON memory | `tests/agent_runtime/test_agentic_integration.py` | Covered |

## GitHub

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| `bea:fix` / bug labels | Classified as actionable bug | Existing issue classifier tests | Partial |
| `bea:research` | Classified as research | Existing issue classifier tests | Partial |
| `bea:security` | Human approval required | Existing issue classifier tests | Partial |
| `bea:no-auto-merge` | No auto-merge capability exists in mission loop | `agent_github/mission_loop.py` | Covered |
| PR draft | Draft is default and preserved | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| Missing tests | PR body creation requires tests run | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| P1/P0 risk | Review gate blocks | `tests/agent_runtime/test_agentic_hardening.py` | Covered |
| Structured PR body | Plan/tests/risks/verdict included | `tests/agent_runtime/test_agentic_integration.py` | Covered |

## Research

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Report without source | Rejected by report validation | Existing research tests | Covered |
| Claims sourced | Claims require `source_ref` | Existing research tests | Covered |
| Confidence | Bounded confidence on claims/report | Existing research tests | Covered |
| Risks | Report includes limitations/risks | Existing research tests | Covered |
| Optional issue proposal | Created only when confidence allows | Existing research tests | Partial |

## Data

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| SELECT allowed | Read-only query accepted | Existing data tests | Covered |
| UPDATE/DELETE/DROP/ALTER blocked | Mutating SQL rejected | Existing data tests | Covered |
| Multi-statement blocked | Semicolon second statement rejected | Existing data tests | Covered |
| Explanation required | Query is explained before execution | Existing data tests | Covered |
| Result limit | LIMIT added or enforced | Existing data tests | Covered |
| Redaction | Output redaction applied in agentic result path | Runtime tests | Partial |

## Self-Improvement

| Scenario | Expected behavior | Evidence | Status |
| --- | --- | --- | --- |
| Reflection creates issue/report | Repeated failure pattern creates issue | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| No direct patch | `creates_direct_patch=False` invariant | `tests/agent_runtime/test_agentic_integration.py` | Covered |
| Risky improvement approval | Security improvements require approval | Existing self-improvement tests | Covered |
| Skill requires tests/source/risk | Skill library validation | Existing self-improvement tests | Covered |
