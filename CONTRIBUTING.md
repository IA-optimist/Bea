# Contributing to BeaMax

Thanks for your interest. This doc is the one-page onboarding for new
contributors (or for yourself six months from now).

## 1. Prerequisites

- **Python 3.11+** (CI matches this exactly — `3.11`)
- **Docker + docker-compose** (local stack : Postgres, Redis, Qdrant)
- **Flutter 3.22.3** (only if touching `beamax_app/`)
- **Node 20+** (only if touching `frontend/`)

## 2. One-time setup

```bash
git clone https://github.com/UniTy01/Beamax-master.git
cd Beamax-master
python3.11 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov pytest-asyncio pytest-xdist ruff mypy pre-commit

# Pre-commit hooks : secret scan + gitleaks + basic hygiene
pre-commit install
```

Environment :

```bash
cp .env.example .env   # fill in the CHANGE_ME values
```

Or run the stack :

```bash
docker compose up -d postgres redis qdrant   # infra only
python main.py                                # backend on :8000
```

## 3. Development loop

### Run tests

```bash
# Fast gate (~5s)
pytest tests/test_canonical_mission_persistence.py \
       tests/test_api_structure.py \
       tests/test_access_enforcement.py \
       tests/test_kernel.py \
       tests/test_cookie_auth.py

# Full suite (~6min single-threaded, ~2min with -n auto)
pytest tests/ -n auto --cov=core --cov-report=term

# Single test file with verbose
pytest tests/test_my_feature.py -vv
```

### Lint

```bash
# Ruff : must be clean (blocks CI)
ruff check .

# Auto-fix what can be auto-fixed
ruff check . --fix
```

### Type-check

```bash
# Advisory — currently non-blocking in CI, but good to clean as you touch code
mypy core/ --ignore-missing-imports
```

## 4. Making changes

### Branch naming

- `feature/<short-name>` for new features
- `fix/<issue-description>` for bug fixes
- `refactor/<area>` for refactors
- `claude/<session-name>` for AI-assisted work

### Commit messages

Follow the existing repo style — present tense, concise, no emoji :

```
fix(auth): cookie expiration race in refresh handler

The JWT refresh path reused the old expiration from the client-provided
cookie instead of recomputing ; under concurrent refresh attempts this
caused early logouts.

Reproduced with test_concurrent_refresh (previously passing only because
of timing luck). Now uses server time.
```

Prefix conventions : `feat`, `fix`, `docs`, `test`, `refactor`, `ops`,
`ci`, `polish`, `security`.

### PRs

- One logical change per PR (even if it spans multiple files)
- Tests for any new behavior — target `core/*` coverage ≥ 48% (enforced)
- Update `docs/` if the change affects public contracts or deployment
- Run the gate tests before pushing : CI runs them anyway, but local
  catches save a round-trip

## 5. Architecture landmarks

| Concern              | Where it lives                              |
|----------------------|---------------------------------------------|
| HTTP API             | `api/main.py`, `api/routes/*`               |
| Mission orchestration| `core/meta_orchestrator.py`                 |
| Kernel contracts     | `kernel/contracts/*`                        |
| LLM factory          | `core/llm_factory.py`                       |
| Memory (RAG)         | `memory/`, `core/memory_facade.py`          |
| Self-improvement     | `core/self_improvement/`                    |
| Agents               | `agents/`, `agents/bea_team/`            |
| Business automation  | `business/`, `core/business/`               |
| Security (hex)       | `mcp/hexstrike-ai/`, `mcp/hexstrike_v2/`    |
| Frontend React       | `frontend/`                                 |
| Mobile Flutter       | `beamax_app/`                            |
| Tests                | `tests/`                                    |
| Infrastructure docs  | `docs/DEPLOYMENT_GUIDE.md`                  |
| API versioning       | `docs/API_VERSIONING.md`                    |

### Structure rules (audit 2026-06)

- **Top-level freeze** : the repo already has 50+ top-level directories.
  Do NOT create a new top-level directory — new code goes into an existing
  package (`core/<area>/`, `api/routes/`, `business/`, ...). If you think a
  new top-level is justified, document why in `ARCHITECTURE.md` in the same
  PR.
- **No micro-packages** : a package of 1–3 files that mirrors an existing
  concept (`monitoring` / `observability` / `observer`, `workflow` vs
  `core/workflow_runtime.py`) is debt, not structure. Extend the existing
  one. Consolidation plan : `docs/refactor/consolidation_plan.md`.
- **File size** : new modules should stay under ~800 lines ; if a file you
  touch exceeds 1000 lines, prefer extracting a focused module over growing
  it (split plan for the worst offender :
  `docs/refactor/meta_orchestrator_split.md`).

### Error handling & logging standard (audit 2026-06)

The codebase has ~2900 `except Exception` blocks. For new/touched code :

- **Never swallow silently** : every `except Exception` must at minimum
  `log.warning(...)` with enough context (mission id, agent, step) to
  diagnose later.
- **Re-raise what must stop the world** : config errors, auth/security
  failures and DB-schema errors must propagate, not be absorbed by a
  resilience loop.
- **Catch narrow when you know** : prefer `except (TimeoutError, OSError)`
  over `except Exception` when the failure mode is known.
- **structlog, not print()** : `print()` is for CLI entrypoints only
  (`orchestrate-cli/`, scripts). Library/server code uses `structlog`.

## 6. Ops quick reference

These scripts run on **VPS1 as root** (never from sandbox/CI) :

- `scripts/verify_prod.sh` — read-only health diagnostic
- `scripts/rotate_secrets.sh` — interactive secret rotation
- `scripts/backup_db.sh` — daily DB backup (meant for cron)
- `scripts/restore_db.sh` — restore from a backup (interactive, destructive)
- `scripts/migrate_to_nonroot.sh` — container UID=1000 migration

See each script's header for usage and safety details.

## 7. Secrets policy

- **Never** commit secrets. Pre-commit hooks (detect-secrets + gitleaks)
  will block commits containing known secret patterns.
- `.secrets.baseline` tracks accepted-as-non-secret occurrences (e.g. test
  fixtures). Audit new entries before adding.
- If a secret is accidentally committed : assume compromised, rotate via
  `scripts/rotate_secrets.sh` and `git filter-branch` / BFG cleanup.
- Flutter builds use `--dart-define` injection (see `.github/workflows/flutter_apk.yml`).

## 8. CI gates

Every PR must pass :

- `ruff check .` — lint (strict subset, see `ruff.toml`)
- `pytest tests/` — all tests + coverage ≥ 48% on `core/`
- `pre-commit` hooks — secret scanning, YAML valid, no merge conflict
  markers, no large files
- `mypy core/` — advisory (won't block, but visible)

## 9. Known debt

Tracked in the codebase (see `ruff.toml` header + `docs/archive/`) :

- **F821** (~472) : undefined names in `mcp/hexstrike-ai/` after module
  split — needs surgical per-file import fixes
- **mypy** : 875 baseline errors with non-strict mode — dedicated cleanup
  sprint needed before we can turn strict
- **v1 API** : 3 routers still alive for legacy clients — sunset plan in
  `docs/API_VERSIONING.md`

## 10. Getting help

- Open an issue on GitHub
- Check `docs/INDEX.md` for the doc map
- Ask in the project Slack/Discord (if applicable)
