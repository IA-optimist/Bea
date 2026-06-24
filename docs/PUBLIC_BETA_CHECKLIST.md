# Béa — Public Beta Checklist

> Pre-release checklist for the Béa Developer Preview. Every item must be
> checked before a public beta release.

---

## Observability

- [x] Redactor (`core/observability/redactor.py`) — secrets never in logs
- [x] MissionEvent (`core/observability/mission_event.py`) — lightweight structured event
- [x] Mission status report (`scripts/mission_status_report.py --json`)
- [x] 26 observability tests (redactor + MissionEvent + report logic)
- [x] No external telemetry (no Sentry, OTEL, Datadog, Prometheus)

## Memory hygiene

- [ ] `python scripts/seed_bea_memory.py --report --profile public` returns `public_safe: True`
- [ ] `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` shows 0 private items in public seed
- [ ] No private jokes in public seed
- [ ] No personal data in public seed
- [ ] No API keys or tokens in seed content
- [ ] `--apply` aborts with exit code 2 (no bypass)

## Documentation

- [ ] `README_PUBLIC_BETA.md` is up to date
- [ ] `docs/BETA_TESTER_GUIDE.md` is accurate
- [ ] `docs/FEEDBACK_GUIDE.md` is accurate
- [ ] `docs/KNOWN_LIMITATIONS.md` is current
- [ ] `docs/PRIVACY_FOR_TESTERS.md` is accurate
- [ ] `docs/TROUBLESHOOTING.md` covers common issues
- [ ] No "production ready" or "stable" claims anywhere
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
- [x] `python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json` passes
- [x] `python scripts/check_internal_imports.py` reports 0 broken_unprotected imports
- [x] Policy decision constants centralized (`core.execution_policy.Decision`)
- [ ] `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` runs clean on public seed

## Identité d'exécution vs identité d'audit

| Champ | Rôle | Source | Utilisé par |
|---|---|---|---|
| `submitted_by` | Identité d'exécution | `get_authenticated_principal()` à la soumission | PolicyEngine, ToolExecutor |
| `approved_by` | Audit uniquement | `get_authenticated_principal()` à l'approval | Logs, historique |
| `rejected_by` | Audit uniquement | `get_authenticated_principal()` au rejet | Logs, historique |

⚠️ `approved_by`/`rejected_by` ne sont **jamais** passés à `PolicyEngine`, `ToolExecutor`, `MetaOrchestrator.run_mission` ou tout mécanisme d'exécution.

## Session Store PolicyEngine

| Backend | Cas d'usage | Multi-worker |
|---|---|---|
| `InMemorySessionStore` | dev/test uniquement | ❌ Non (état local au process) |
| `RedisSessionStore` | beta/prod | ✅ Oui |

**Pour beta publique : `POLICY_SESSION_STORE=redis` requis.** Si Redis indisponible et mode redis → démarrage refusé (fail-closed).

- [ ] `POLICY_SESSION_STORE=redis` configuré et Redis opérationnel en beta/prod
- [ ] `InMemorySessionStore` bloqué si `BEA_PRODUCTION=true`
- [ ] Clé de session = `principal_id:mission_id` — jamais `mission_id` seul
- [ ] Abstraction `core/session_store.py` complète et testée (`beta/auth-session-hardening` SOUS-AGENT B — en cours 2026-06-24)

## Policy / risk guardrails

- [x] `core/tool_executor.py` uses `Decision` constants and blocks `REQUIRES_APPROVAL`/`BLOCKED`
- [x] Policy-unavailable fallback blocks `execute` / high-risk tools
- [x] `RiskEngine.analyze()` exception falls back to `HIGH` / blocked
- [x] Artifact validator rejects code missions without verifiable artifact evidence
- [x] `PolicyEngine` enforces shared session/economic limits end-to-end — `evaluate_tool()` calls `ensure_session()` + atomic `check_and_record()`; explicit limits override mode presets; sessions are evicted after timeout and capped; empty/`None` `mission_id` is denied; `_session_key()` supports optional `principal_id`; `ToolExecutor`/`MetaOrchestrator`/`BeaOrchestrator` use the `get_policy_engine()` singleton and inject `mission_id` (`fix/policy-engine-session-hardening`)
- [x] `mission_id` propagation audited end-to-end — 3 runtime gaps fixed (missions route, tool_pipeline, recovery key), ratchet `scripts/check_tool_executor_mission_id.py` guards against regression, 9 tests cover propagation invariants (PR fix/mission-id-propagation-audit)
- [x] Authenticated principal binding end-to-end — validated identity is extracted from `request.state.user` via `api/auth_principal.py`, propagated through routes → `KernelAdapter` → `MetaOrchestrator`/`BeaOrchestrator` → `tool_runner` → `execution_engine` → `tool_pipeline_tool` → `PolicyEngine`; public routes overwrite client-supplied `principal_id`; `_bea_principal_id` is the trusted params key; ratchet `scripts/check_policy_principal_binding.py` guards against regression (`feat/principal-auth-binding`)
- [x] Mission submitter identity persists across approval/resume — `submitted_by` is stored on `MissionResult`, `MissionContext`, and `PersistedMission` at submit time; public routes derive it from authenticated context and fail-closed when auth is required; approval/resume paths run the mission under `submitted_by` for PolicyEngine session binding; `approved_by` is stored separately for audit; ratchets and new tests in `tests/test_mission_submitted_by.py` guard regression (`fix/mission-submitted-by`)
- [x] Approval queue auth hardened — `approved_by`/`rejected_by` derived from `get_authenticated_principal()` on all routes; hardcoded `"human"` removed from `api/mission_approval.py`; `reject_mission` route now passes `rejected_by` from auth context; `core/approval_queue` defaults changed from `"human"` to `None`; ratchet `scripts/check_approval_hardcoded_principals.py` prevents reintroduction (`fix/approval-queue-auth`)

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
rg "production ready|stable public beta|guaranteed" docs README_PUBLIC_BETA.md
```
