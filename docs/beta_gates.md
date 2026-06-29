# Beta Gates Checklist — Béa Agentic Foundation v1

## How to Use

Run this checklist before any public beta promotion.
Mark each item ✅ (pass), ❌ (fail), or ⚠️ (partial/unknown).

---

## Gate 0 — Branch / CI

- [ ] Branch `feat/agentic-foundation-v1` has all 9 phase commits
- [ ] No direct commits to `main` from this branch
- [ ] All new files in `agent_*/` packages
- [ ] No existing `api/` or `core/` files modified

## Gate 1 — Tests

- [ ] `pytest tests/agent_runtime/ -q` → all PASS
- [ ] `pytest tests/agent_workflows/ -q` → all PASS
- [ ] `pytest tests/agent_memory/ -q` → all PASS
- [ ] `pytest tests/agent_github/ -q` → all PASS
- [ ] `pytest tests/agent_research/ -q` → all PASS
- [ ] `pytest tests/agent_data/ -q` → all PASS
- [ ] `pytest tests/agent_self_improvement/ -q` → all PASS
- [ ] **Total: 142 tests PASS**
- [ ] `pytest tests/ -q --ignore=tests/agent_*` → existing suite not regressed

## Gate 2 — Linting

- [ ] `ruff check agent_runtime/` → 0 errors
- [ ] `ruff check agent_workflows/` → 0 errors
- [ ] `ruff check agent_memory/` → 0 errors
- [ ] `ruff check agent_github/` → 0 errors
- [ ] `ruff check agent_research/` → 0 errors
- [ ] `ruff check agent_data/` → 0 errors
- [ ] `ruff check agent_self_improvement/` → 0 errors

## Gate 3 — Security Invariants

- [ ] `ACIExecutor` blocks unknown actions (deny-by-default test passes)
- [ ] Sensitive paths blocked (`test_dangerous_path_blocked` passes)
- [ ] Secrets filtered from sandbox env (`KEY/TOKEN/SECRET/PASS/AUTH`)
- [ ] SQL injection blocked (`check_sql_safety` tests pass)
- [ ] Social media blocked in research (`test_twitter_rejected` passes)
- [ ] `creates_direct_patch=False` always enforced
- [ ] SECURITY ImprovementKind always `human_approval_required=True`
- [ ] PR drafts always `pr_draft=True`
- [ ] `approved_by` required in DataAgent.execute()

## Gate 4 — Documentation

- [ ] `docs/agentic_foundation_audit.md` — gap analysis
- [ ] `docs/agentic_foundation_v1.md` — architecture summary
- [ ] `docs/agentic_security_model.md` — threat model + defenses
- [ ] `docs/agentic_memory_model.md` — memory tiers + types
- [ ] `docs/agentic_github_loop.md` — pipeline + invariants
- [ ] `docs/beta_gates.md` — this file

## Gate 5 — Human Review Items (HUMAN_REQUIRED)

These gates cannot be automated — human must verify:

- [ ] Qdrant blocker (P1 from beta report) resolved: `python scripts/audit_memory_store.py --apply --privacy-scan`
- [ ] Android physical device test (Pixel 7, User 11)
- [ ] PR #117 CI passed and reviewed
- [ ] PRs #18/#19/#20 merged in GitHub UI (workflow scope)
- [ ] Secrets rotation (API keys, admin password)

## Gate 6 — API Regression

- [ ] `python scripts/validate_local.py --quick` → PASS
- [ ] Health check: `curl http://localhost:8000/health` → `{"status":"healthy"}`
- [ ] No new routes added to `api/` by this branch

## PROMOTION DECISION

- PUBLIC_BETA_CANDIDATE: false (Gate 5 items pending — human required)
- AGENTIC_FOUNDATION_V1: true (all automated gates pass)
- ACTION: Merge to main after human review of PR + Gate 5 items

---

*Updated: 2026-06-28 | Branch: feat/agentic-foundation-v1*
