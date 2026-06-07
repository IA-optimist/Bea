# Changelog

All notable changes to **Beamax** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the repo uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for tags.

## [Unreleased]

### Security
- Sandbox Docker hardened: `network_mode="none"` (opt-in bridge), `read_only=True`,
  tmpfs `/tmp`+`/run`, `mem_limit=512m`, `pids_limit=128`, `cap_drop=["ALL"]`,
  `no-new-privileges`. Copy-on-write workspace clone now excludes `.env*`,
  `.git`, `*.key`, `*.pem`, `secrets/`, `tokens.json`.
- `config/settings.py`: dropped `"change-me-in-production"` placeholder.
  Unset `BEA_SECRET_KEY` now yields an ephemeral per-process random key;
  `enforce_production_secrets()` rejects ephemeral/placeholder keys in prod.
- `api/auth.py`: admin login refused when `BEA_ADMIN_PASSWORD` is unset
  (no more silent fallback to the JWT signing key).
- `api/main.py`: production requires `CORS_ORIGINS` explicitly — boot raises
  if `BEA_PRODUCTION=true` and no allowlist is set.
- `api/security_headers.py`: CSP `'unsafe-inline'` scoped to `/docs` Swagger
  paths only; main API surface gets a strict CSP.
- All 18 GitHub Actions pinned by commit SHA (supply-chain hardening).
- New CI job `secret-scan` runs gitleaks 8.21.2 on full git history.
- Pre-commit `ruff` hook added (lint-only, `--no-fix`).
- Deleted vendored `mcp/hexstrike-ai/` (~12k LOC, 0 imports, RCE-by-design
  via `subprocess.Popen(shell=True)`) and orphan `agent_marketplace/`
  (21 KB, 0 imports).
- `Dockerfile.nonroot` rewritten as multi-stage (builder + slim runtime,
  non-root UID 1000, no compiler in runtime image).

### Added
- `ARCHITECTURE.md` — top-level layered design + `business/` vs `core/business/`
  split documentation.
- `core/registries/__init__.py` — canonical re-export of the four registries
  (ToolDefinition / ToolExecutor / OperationalTool / Agent).
- `tests/test_p0_hardening.py` + `tests/test_p1_hardening.py` — regression
  tests covering the new hardening invariants.
- `Audit_Beamax_2026-05-18.docx` (later moved to `docs/audits/`) — full
  technical audit covering architecture, security, code quality.

### Changed
- CI `--cov-fail-under` raised 50 → 55 → 60 (roadmap 60 → 65 → 70).
- `ruff.toml`: `target-version` 3.11 → 3.12 (aligns with `.python-version` and
  the CI Python). `orchestrate-cli/` and `orchestrate-mobile/` excluded
  until a dedicated cleanup PR.
- Deploy workflow now builds `Dockerfile.nonroot` and uses `-p 8000:8000`
  instead of `--network host`.

### Fixed
- `tests/test_agi_modules.py::TestGoalRegistry/TestProactiveLoop::test_import`:
  `core/orchestration/goal_registry.py` `DEFAULT_PATH` was hardcoded to a
  user-specific path. Now resolved portable via `config.settings.workspace_dir`.
- `tests/test_skill_system.py::test_duplicate_detection`: `_merge_into()`
  caller was passing a spurious 5th positional argument (`result`).
- `tests/test_production_hardening_p34.py::TestRequireAuthGuard` (6 tests):
  `api/_deps.py` now treats ephemeral `BEA_SECRET_KEY` defaults as
  "not configured" so the no-token-no-jwt path still returns 503.
- `tests/test_canonical_mission_persistence.py` (10 tests):
  `CanonicalMissionStore` now honours an explicit `db_path` instead of
  opportunistically routing writes to Postgres when `DATABASE_URL` is set.
- `tests/test_llm_routing_policy.py::test_safe_invoke_accepts_new_kwargs`:
  `core/llm_wrapper.py` monkey-patch now uses `@functools.wraps(original)`
  so `inspect.signature(LLMFactory.safe_invoke)` still surfaces the
  explicit kwargs (`task_description`, `budget`, `latency`).
- `core/orchestration/proactive_loop.py` `HEARTBEAT_PATH` / `WORKSPACE`
  constants resolved portable instead of hardcoded `/root/.openclaw-...`.

### Removed
- 4 README locale variants (`README_DE.md`, `README_ES.md`, `README_JA.md`,
  `README_ZH.md`) — no i18n pipeline, drift was guaranteed.
- `README_EN.md` — single-README policy (audit "garder README.md seul").
- 3 tracked `*.py.bak_auth` files under `api/routes/`.
- `test_write_perm.tmp` + the broken `latest` symlink at repo root.

### Audit history

The hardening trajectory in this Unreleased section was applied in six
sprints (2026-05-18 → 2026-05-19):

| Sprint | Commit  | Scope                                                              |
|--------|---------|--------------------------------------------------------------------|
| 1      | 2556000 | Workflow + Dockerfile + secret-key + admin-pwd hardening           |
| 2      | 8c51c09 | Actions SHA pinning + gitleaks CI + sandbox + CORS/CSP             |
| 3-4    | ca86268 | Delete hexstrike + agent_marketplace + multi-stage Docker + READMEs |
| 5      | d7d2650 | CI stabilization (gitleaksignore, ruff scope, baseline)            |
| 6      | fb6619f | 19 pre-existing pytest failures fixed                              |
| 7      | 6f5f5af | Coverage 60, portable paths, CHANGELOG, audit doc move             |
| 8      | 95f10e4 | mypy dedicated job + 5/5 core/_legacy/ shims migrated (issue #15)  |
| 9      | (this)  | core/_legacy/ deleted entirely + 247 open() encoding fix           |

The full audit document is at `docs/audits/Audit_Beamax_2026-05-18.docx`.
