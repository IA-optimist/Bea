# Audit Roadmap — Progress Log

Tracks the full-stack consolidation sweep across multiple AI-assisted
sessions. Each phase is a landed PR on `main`.

## Completed

### Phase 1 — Initial audit + cookie auth XSS fix
- CVSS 9.1 XSS mitigation via HttpOnly cookie auth (backend middleware,
  React api client, Flutter secure storage, static/app.html)
- 13 CVE bumps in `requirements.txt`
- HexStrike `hexstrike_server.py` decomposition (17 290 → 821 lines)
  via AST-based class extraction + backward-compat re-exports
- Pre-commit hooks : `detect-secrets` v1.5.0 + `gitleaks` v8.21.2 +
  private-key + merge-conflict + large-files
- Dependency inversion core ← api (no more core importing api)
- 13-phase test fix sweep (final suite : 4906 passed, 67 xfailed)

### Phase 2 — Ops + polish + workflows
- `scripts/rotate_secrets.sh` (9-step interactive rotation)
- `scripts/verify_prod.sh` (read-only diagnostic)
- `scripts/migrate_to_nonroot.sh` (container UID=1000 migration)
- `scripts/backup_db.sh` + `scripts/restore_db.sh` (pg_dump + Redis RDB
  + canonical.db + rotation 7 daily / 4 weekly / 3 monthly)
- `Dockerfile.nonroot`
- `.github/workflows/flutter_apk.yml` (APK build on tag `v*`)
- `.github/dependabot.yml` (weekly PRs for pip + actions + pub)
- `core/llm_response_cache.py` (Redis + in-memory LRU, 8 tests)
- `core/profiling.py` (Prometheus + structlog spans, 7 tests)
- `CONTRIBUTING.md`, `docs/API_VERSIONING.md`
- `ruff.toml` with progressive strict rule set
- CI speedup via `pytest-xdist -n auto`
- Coverage threshold 45% → 48%
- `datetime.utcnow()` → `datetime.now(timezone.utc)` across 20 files
- 20 files archived from `docs/` to `docs/archive/` + `docs/INDEX.md`

### Phase 3 — hexstrike-ai F821 cleanup
- 472 F821 undefined-name errors across 22 modules → 0
- 66 proper cross-module imports added via automated patch script
- 8 surgical fixes : nested f-string escaping, API_HOST/PORT relocation,
  self-prefix removal, venv import, Options → ChromeOptions
- `F821` now **blocking** in CI

### Phase 4 — Ratchet ruff rule set
Added to the blocking select :
- `F401` unused-import (17 probe-imports marked `# noqa`)
- `F811` redefined-while-unused (2 fixes)
- `F841` unused-variable (169 auto-fixes)
- `E711` / `E712` / `E713` / `E714` comparison variants
- `E722` bare-except (6 fixes : `except:` → `except Exception:`)

### Phase 5 — Coverage uplift (mission_system)
- `tests/test_mission_system_classifiers.py` (23 tests covering pure
  routing helpers : `is_capability_query`, `detect_intent`,
  `classify_action`, `compute_risk_score`, `risk_score_to_level`,
  `compute_complexity`, `evaluate_approval`)

### Phase 6 — Coverage uplift (event_stream)
- `tests/test_event_stream.py` (15 tests : append/order/bounded-deque,
  subscribe/unsubscribe/idempotent, error-isolation, rewind, mission
  registry, ws registry)

### Phase 7 — Coverage uplift (approval_queue)
- `tests/test_approval_queue.py` (12 tests : auto-approve READ /
  WRITE_LOW, require approval for HIGH/INFRA/DELETE/DEPLOY, approve,
  reject, get_pending, dedup, persistence)
- `tests/test_canonical_types_transitions.py` (10 tests : terminal
  state invariants, no self-transition, legacy mappers)
- 3 test regressions fixed : `test_meta_orchestrator.test_setup_event_
  stream` (api.ws.register_stream → core.event_stream.register_ws_
  stream), `test_stabilization_final.test_no_report_files_at_root`
  (CONTRIBUTING.md allowed at root), `test_consolidation.test_check_
  auth_missing_token` (_check_auth moved to api._deps)

### Phase 8 — Final ratchet
- E731 lambda-assignment (5 fixes auto-converted to def)
- E401 multiple-imports-on-one-line (1 fix)
- Both rules added to blocking ruff select
- Coverage threshold bumped 48% → 50%
- Security review (sub-agent) : 0 vulnerabilities found in the diff

### Autonomy Foundation (5 layered modules, 99 tests)
- `core/autonomy/event_bus.py` (12 tests) — in-process pub/sub
- `core/autonomy/budget.py` (11 tests) — per-mission + daily caps
- `core/autonomy/daemon.py` (17 tests) — goal-driven loop with stop conditions
- `core/autonomy/skills.py` + builtin_skills.py (11 tests) — registry + 5 defaults
- `core/autonomy/learning.py` (9 tests) — EWMA outcome aggregator
- `core/autonomy/multi_choice.py` (17 tests) — HITL beyond approve/reject

### Autonomy Wiring (real-orchestrator integration)
- `core/autonomy/runners.py` — meta_orchestrator_runner, composite_runner
- `core/autonomy/planners.py` — objective_engine_planner, learner_aware_planner, chain_planner
- `core/autonomy/approval_bridge.py` — StrategyChoice + request_strategy_choice
- `api/routes/autonomy.py` — /api/v3/autonomy/{start, stop, status, decisions}
  with feature flag `JARVIS_AUTONOMY_USE_REAL=1` to switch from safe to real mode
- `tests/test_autonomy_api.py` (11 tests) — FastAPI TestClient
- 22 wiring tests in `tests/test_autonomy_wiring.py`

### Autonomy Production Wiring
- `jarvismax_app/lib/models/autonomy_decision.dart` + `screens/decisions_screen.dart`
  Mobile UI : list pending decisions, tap to choose, with risk badges
- ApiService.fetchPendingDecisions / answerDecision / fetchAutonomyStatus
- Approvals screen → tap icon → DecisionsScreen
- `deploy/jarvis-autonomy.service` — systemd unit that POSTs /start at boot
- `scripts/install_autonomy.sh` — interactive installer with smoke test
- `docs/AUTONOMY.md` — operator guide

## Remaining debt (explicitly tracked)

| Rule / Area         | Count  | Severity | Recommended fix |
|---------------------|--------|----------|-----------------|
| `E701` (multi-stmt colon)    | ~78 | cosmetic | Manual split, not auto-safe |
| `E702` (multi-stmt semi)     | ~37 | cosmetic | Manual split |
| `E731` (lambda-assignment)   | 5   | cosmetic | Convert to `def` |
| `E741` (ambiguous l/I/O)     | ~78 | cosmetic | Rename vars manually |
| `E402` (import not at top)   | ~127 | mostly intentional (lazy imports to break circular deps) |
| mypy strict coverage         | 875 baseline errors | large | Dedicated sprint |
| v1 API sunset                | 3 routers | medium | After mobile app migrates to v2/v3 |
| Frontend UX polish           | — | feature | Needs product direction |
| Docstring completeness       | ~1200 D-rule errors | cosmetic | Optional |
| Type annotations             | ~8100 ANN rule errors | medium | Progressive |

## Operational checklist for production

Must be executed by the operator on VPS1 — cannot be done from
sandbox / CI. Status tracked independently of the code roadmap.

- [ ] `bash scripts/verify_prod.sh --verbose` — baseline diagnostic
- [ ] `bash scripts/rotate_secrets.sh` — revoke leaked tokens, rotate
      JARVIS_SECRET_KEY, POSTGRES_PASSWORD, N8N_ENCRYPTION_KEY,
      OPENROUTER_API_KEY
- [ ] `bash scripts/backup_db.sh` — install in cron
      `0 3 * * * /root/Jarvismax-master/scripts/backup_db.sh >> /var/log/jarvis_backup.log 2>&1`
- [ ] `bash scripts/migrate_to_nonroot.sh` — container UID=1000 (brief downtime)
- [ ] Configure GitHub Actions secrets for Flutter APK build :
      `JARVIS_API_TOKEN`, `JARVIS_API_HOST`, `JARVIS_API_PORT`,
      `JARVIS_USERNAME`
- [ ] Optional : Android keystore secrets for signed APK :
      `ANDROID_KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`,
      `KEY_PASSWORD`
- [ ] Tag `v1.1.0` to trigger first APK release build
- [ ] Monitor prod for 24h post-migration

## Architecture principles established

- **Kernel Rule K1** : `kernel/` never imports from `core/`, `api/`,
  `agents/`, `tools/`. Inversion : `core/` submits to kernel via
  `register_orchestrator()`.
- **Kernel Rule K2** : all memory access through `core/memory_facade.py`.
  Direct layer access (`memory.memory_bus`, `memory.qdrant_client`) is
  fallback only.
- **Auth model** : HttpOnly cookie + SameSite=Lax + Secure (HTTPS only).
  JWT access tokens + static `JARVIS_API_TOKEN` support kept for legacy
  callers.
- **Secrets policy** : pre-commit blocks commits with secret patterns.
  `.secrets.baseline` whitelists test fixtures. Rotation via
  `scripts/rotate_secrets.sh`.
- **Lint gate** : ruff with a progressive `select` set. New code must
  be clean on the currently-enabled rules.
- **Type gate** : mypy runs non-blocking for now. Strict is a separate
  effort.
- **Coverage gate** : `core/` ≥ 48%. Raise by 2% per phase.
