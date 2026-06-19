# Self-Improvement Policy

This document defines the policy governing Béa's automated self-improvement.
It complements the threat model in `threat_model_merge.md` and the implementation
in `core/self_improvement/`.

## Principles

1. **Human review by default**: every patch starts as a proposal.
2. **Never auto-merge protected areas**: kernel, auth, security, payments, CI, deployment.
3. **Guardrails are invariants**: cooldown, max failures, protected paths, and sandboxing cannot be weakened by a patch.
4. **Proof through harness**: a patch is promoted only if reproducible tests prove it safe.
5. **Rollback must remain possible**: every auto-applied patch must have a tested rollback path.

## Modes

### `propose`

- The daemon detects weaknesses and writes a spec/patch to `workspace/self_improvement/proposals/`.
- No code is changed automatically.
- A human must review the proposal and open a PR manually.

### `merge`

- The daemon creates a feature branch in a clean worktree.
- It applies the patch, runs lint/tests/harness, and opens a PR.
- **It never merges automatically** — it only proposes a PR on the agent's own branch.
- The promotion pipeline can also apply the patch to a throwaway sandbox and validate it.

## Protected paths

Auto-merge is **forbidden** for any patch that touches:

- `kernel/`
- `core/security/`
- `core/auth*` and `api/auth.py`
- `api/_deps.py`
- `api/middleware.py`
- `config/settings.py`
- `.github/workflows/`
- `deploy/`
- `core/finance/` and `business/revenue/`
- `kernel/improvement/gate.py`
- `scripts/validate_local.py`

These paths are enforced in `core/self_improvement/protected_paths.py`. A patch touching a protected path is downgraded to `propose` mode regardless of mode setting.

## Gate rules (invariants)

Defined in `kernel/improvement/gate.py`:

| Invariant | Value | Purpose |
|---|---|---|
| `MAX_PER_RUN` | 1 | Prevent runaway loops |
| `COOLDOWN_HOURS` | 24 | Limit blast radius |
| `MAX_FAILURES` | 3 | Auto-pause after consecutive failures |

These values are constants in kernel code. They can only be changed by a human PR.

## Approval rules by risk

| Risk | `AUTO_APPROVE_MEDIUM=0` | `AUTO_APPROVE_MEDIUM=1` |
|---|---|---|
| LOW (read-only queries) | auto-approved | auto-approved |
| MEDIUM (safe writes, tool calls) | requires human approval | auto-approved with rollback |
| HIGH (file delete, deploy) | requires human approval | requires human approval |
| CRITICAL (auth, payments, kernel) | requires human approval | requires human approval |

## Patch lifecycle

```
detect weakness
    ↓
plan patch
    ↓
create git worktree (from core/self_improvement/git_agent.py)
    ↓
apply patch
    ↓
run ruff + pytest + harness + validate_local
    ↓
generate PR with diff and score
    ↓
if protected path touched → human review required
    ↓
if all gates green and not protected → open auto-PR
```

## Signing requirement

Once implemented (Task 4 Step 4 of the consolidation roadmap), every auto-applied patch must carry a cryptographic signature. The promotion pipeline rejects unsigned patches or patches whose signature does not verify against the known agent key.

## Monitoring and audit

- Every gate decision is logged with `mission_id`, `reason`, `timestamp`, and `consecutive_failures`.
- Every auto-approved action emits an `auto_approved_action` event with full provenance.
- `scripts/verify_prod.sh` includes a self-improvement audit check.

## Emergency stop

Set `BEA_IMPROVEMENT_MODE=propose` or `BEA_SKIP_IMPROVEMENT_GATE=1` in the environment to disable automatic promotion. Removing `AUTO_APPROVE_MEDIUM=1` prevents MEDIUM-risk auto-approval.

## Responsibilities

- **Kernel gate** (`kernel/improvement/gate.py`): enforces cooldown, failure limits, and security check.
- **Promotion pipeline** (`core/self_improvement/promotion_pipeline.py`): runs tests, opens PRs, never merges protected paths.
- **Protected paths** (`core/self_improvement/protected_paths.py`): mechanical deny-list.
- **Operator**: reviews all PRs touching protected paths and maintains secret rotation.
