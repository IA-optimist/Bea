# Public Beta Checklist

PUBLIC_BETA_READY: false

This file mirrors the root [PUBLIC_BETA_CHECKLIST.md](../PUBLIC_BETA_CHECKLIST.md).

## Required Before Open Beta

- [ ] Qdrant live privacy scan proves 0 private items.
- [ ] Historical/shared secret rotation is proved by the owner.
- [ ] Android mission UI is validated on a physical device.
- [ ] Android offline/network-failure behavior is validated on a physical
  device.
- [ ] `RedisSessionStore` is configured for multi-process or multi-worker use.
- [ ] Full validation and docs truth gate pass.
- [ ] No current docs claim more than the evidence proves.

## Observability

- [x] Redactor (`core/observability/redactor.py`) — secrets never in logs
- [x] MissionEvent (`core/observability/mission_event.py`) — lightweight structured event
- [x] Mission status report (`scripts/mission_status_report.py --json`)
- [x] 26 observability tests (redactor + MissionEvent + report logic)
- [x] No external telemetry (no Sentry, OTEL, Datadog, Prometheus)

## Current Private Beta Position

Private Beta 0.1 can be considered only for 5-10 technical testers under
supervision.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: Qdrant cleanup proof.
- HUMAN_REQUIRED: secret rotation proof.
- HUMAN_REQUIRED: Android physical-device proof.
- [ ] `README_PUBLIC_BETA.md` is up to date
- [ ] `docs/BETA_TESTER_GUIDE.md` is accurate
- [ ] `docs/FEEDBACK_GUIDE.md` is accurate
- [ ] `docs/KNOWN_LIMITATIONS.md` is current
- [ ] `docs/PRIVACY_FOR_TESTERS.md` is accurate
- [ ] `docs/TROUBLESHOOTING.md` covers common issues
- [ ] No maturity overclaims (run `scripts/check_docs_truth.py` to verify)
- [ ] All doc links resolve (no 404s)

## Security

- [ ] `.env` is in `.gitignore`
- [ ] No secrets in any committed file
- [ ] `BEA_CONTINUOUS_IMPROVEMENT=0` by default
- [ ] `BEA_SKIP_IMPROVEMENT_GATE` is not set
- [ ] API authentication is enabled
- [ ] No endpoints exposed without auth (except `/health`)

## Issue templates

- [ ] `.github/ISSUE_TEMPLATE/bug_report.yml` exists
- [ ] `.github/ISSUE_TEMPLATE/beta_feedback.yml` exists
- [ ] `.github/ISSUE_TEMPLATE/security_report.md` exists
- [ ] Templates ask for: OS, commit, steps, expected, actual, redacted logs
- [ ] Templates include category dropdown (API, Flutter, Memory, Provider, Mission, Docs, Unknown)

## Validation gates

- [x] `ruff check .` passes
- [x] `pytest` passes (all critical tests)
- [x] `python scripts/validate_local.py --quick` passes all gates
- [x] CI smoke enforced on PR (fixture-backed, no provider key required)
- [x] `python scripts/bea_eval.py --json --isolated` reproductible (25/25, two runs same score)
- [x] Completion truth gate enforced (`validate_coding_report` + regression tests)
- [ ] `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` runs clean on public seed

## Provider readiness

- [x] OpenRouter free tier works for all 3 roles (forge-builder, scout-research, shadow-advisor)
- [x] Ollama fallback documented (with known limitations)
- [ ] No hardcoded provider keys anywhere in the codebase

## APK / Flutter

- [x] Flutter client uses `/api/v3` only (grep confirmed: 0 active `/api/v1` calls)
- [x] APK build CI workflow (`flutter_apk.yml`) — gate + `workflow_dispatch`
- [x] `scripts/check_client_v1_usage.py` — local v1-gate checker
- [ ] APK v3 validated on physical device

## Known limitations documented

- [x] Router is advisory only (`runtime_enforced=false`)
- [x] Rate-limiting configurable (`BEA_RATE_LIMIT_PER_MINUTE`)
- [x] v1 endpoints maintained for Flutter rollback — timeline in `docs/API_VERSIONING.md`
- [ ] `bea_eval` may timeout on large local stores
- [ ] MissionEvent not yet wired into pipeline_auto (building block only)

## Grep checks

```bash
# Should return nothing:
rg "sk-|OPENROUTER_API_KEY=|Bearer " docs .github README_PUBLIC_BETA.md
# check_docs_truth.py enforces maturity claim patterns automatically
```
