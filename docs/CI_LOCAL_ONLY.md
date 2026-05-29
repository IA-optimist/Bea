# CI runs locally, not on GitHub

**Decision (2026-05-30):** auto-triggered GitHub Actions are disabled to
stop billing. GitHub serves only as the remote backup for the source
code. All validation runs on the developer's machine before push.

## What changed

Every workflow in `.github/workflows/` had its `on: push` / `on: pull_request`
triggers commented out and replaced with `workflow_dispatch` only. The
workflows are still defined and can be re-run manually from the GitHub
Actions UI (if billing is ever re-enabled or for one-off releases).

Affected files:
- `.github/workflows/ci.yml` — main CI/CD pipeline
- `.github/workflows/unit.yml` — unit tests
- `.github/workflows/kernel_ci.yml` — kernel architecture rules
- `.github/workflows/pre-commit.yml` — security pre-commit hooks
- `.github/workflows/flutter_apk.yml` — Flutter APK build
- `.github/workflows/deploy.yml` — VPS auto-deploy

## How to validate before pushing

Use the PowerShell script that runs the same gates as the old CI:

```powershell
.\scripts\validate_local.ps1
```

Output: each check is one section, ✅ pass / ❌ fail / ⏭ skip (tool not
installed). Exits non-zero if any check fails — wire it as a git
pre-push hook to refuse pushes that would have broken CI:

```powershell
# .git/hooks/pre-push (Windows)
& "$(git rev-parse --show-toplevel)\scripts\validate_local.ps1"
```

## What the local script covers

| Check | Tool | What it does |
|---|---|---|
| `ruff` | `ruff` | Lint, the project's blocking rule set |
| lock drift | python | `scripts/check_requirements_lock.py` — pins in `requirements.txt` match `requirements.lock` |
| pytest (hardening) | `pytest` | 12 hardening test files (~100 tests) |
| mypy delta | `mypy` | core/api/kernel error count <= `quality/mypy-baseline.json` |
| bandit delta | `bandit` | Per-test-id count <= `quality/bandit-baseline.json` |
| pip-audit delta | `pip-audit` | No new CVE beyond `quality/pip-audit-baseline.json` (empty) |
| silent-swallow baseline | python | `scripts/generate_silent_swallow_baseline.py` self-check |

Each check is independent — install only what you need. The optional
tools (`bandit`, `pip-audit`, `mypy`) install with:

```powershell
.venv\Scripts\pip install ruff mypy bandit pip-audit detect-secrets `
    structlog pydantic fastapi pydantic-settings
```

## How to re-enable cloud CI

Each workflow's header carries a marker comment:

```yaml
# Auto-triggers disabled 2026-05-30 — see ci.yml header for rationale.
on:
  workflow_dispatch:
  # push:
  #   branches: [ main, develop ]
  # pull_request:
  #   branches: [ main ]
```

Uncomment the `push` / `pull_request` blocks and the workflow goes back
to auto-trigger.

## How to run a workflow manually

If you ever need to run the cloud pipeline once (e.g. for a release):

1. Open https://github.com/IA-optimist/Bea/actions
2. Pick the workflow you want
3. Click **Run workflow** → choose the branch
4. Approve any billing prompts GitHub shows

## Pre-push hook setup (optional, recommended)

```powershell
# From the repo root:
$hook = ".git\hooks\pre-push"
@'
#!/bin/sh
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(git rev-parse --show-toplevel)/scripts/validate_local.ps1"
'@ | Set-Content -Path $hook -Encoding utf8
# No `chmod +x` needed on Windows; Git for Windows treats it as executable.
```

Test it:

```powershell
git commit --allow-empty -m "test"
git push --dry-run
# Should see: "▶ ruff", "✅ pytest passed", etc.
```

## Why this is OK for the project

The hardening session validated every commit locally before push for
27 commits in a row — the cloud CI was effectively duplicating local
checks. The local script captures the exact same logic, runs in <1 minute
total, and costs $0.
