# PUBLIC_BETA_CHECKLIST.md → Private Beta Gate

> This file is the single source of truth for the **private beta** readiness of Béa.  
> It was created/reconciled during the `beta/private-readiness-kilo-kimi` pass on 2026-06-24.

## Honest framing

Béa is currently a **private beta** / **developer preview** / **experimental** system.  
It is **not stable**, **not production-ready**, and **not fully autonomous**.  
This checklist tracks only the gates needed for **5–10 technical testers** in controlled environments.

## Private beta gate status

```yaml
READY_FOR_PRIVATE_BETA: true
READY_FOR_PUBLIC_BETA: false
HUMAN_VALIDATION_REQUIRED:
  - Rotate secrets that may have been exposed historically (JWT_SECRET_KEY, JARVIS_API_TOKEN, OPENROUTER_API_KEY, POSTGRES_PASSWORD).
  - Revoke any hardcoded Flutter API token before distributing an APK (docs/SECURITY_AUDIT.md §8.7).
  - Confirm origin/main CI is green and aligned with cleaned git history.
  - Choose 5–10 testers and provide a private communication channel.
```

## P0 — Must be true before inviting testers

| # | Gate | Expected | Status | Proof / command |
|---|------|----------|--------|-----------------|
| 1 | Self-improvement disabled by default | `self_improve_enabled == false` | ✅ | `python -c "from config.settings import get_settings; print(get_settings().self_improve_enabled)"` → `False` |
| 2 | `BEA_SKIP_IMPROVEMENT_GATE` defaults to false / unset | `bea_skip_improvement_gate == false` | ✅ | `python -c "from config.settings import get_settings; print(get_settings().bea_skip_improvement_gate)"` → `False` |
| 3 | `.env.example` ships safe defaults | `SELF_IMPROVE_ENABLED=false`, `JARVIS_PRODUCTION=false`, no active skip gate | ✅ | `rg 'SELF_IMPROVE_ENABLED=false' .env.example` and `rg '^[^#]*BEA_SKIP_IMPROVEMENT_GATE\s*=\s*(1|true|yes)' .env.example` → empty |
| 4 | `.gitignore` ignores env files | `.env`, `.env.production`, `.env.*.local` present | ✅ | `rg '^\.env' .gitignore` |
| 5 | No hardcoded cloud secrets in tracked source | 0 real secrets | ✅ | `python scripts/private_beta_gate.py --json` → `secret_scan` blockers empty |
| 6 | Auth required everywhere except `/health` (and static login assets) | `/health` public, sensitive routes protected | ✅ | `python -c "from api.access_enforcement import is_public_path; print(is_public_path('/api/v3/missions'), is_public_path('/health'))"` → `False True` |
| 7 | Public memory seed is clean | `public_safe == true`, 0 private items | ✅ | `python scripts/seed_bea_memory.py --report --profile public` |
| 8 | Memory store privacy scan is clean | `clean == true` | ✅ | `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` |
| 9 | Private-beta gate script passes | `ready_for_private_beta == true` | ✅ | `python scripts/private_beta_gate.py --json` → `ready_for_private_beta: true` |
| 10 | Required beta docs exist | All files below present | ✅ | `ls README_PUBLIC_BETA.md docs/BETA_TESTER_GUIDE.md docs/FEEDBACK_GUIDE.md docs/KNOWN_LIMITATIONS.md docs/PRIVACY_FOR_TESTERS.md docs/TROUBLESHOOTING.md docs/PRIVATE_BETA_RUNBOOK.md PUBLIC_BETA_CHECKLIST.md` |
| 11 | Issue templates exist | Bug, feedback, security templates | ✅ | `ls .github/ISSUE_TEMPLATE/*.yml .github/ISSUE_TEMPLATE/*.md` |
| 12 | Lint passes | `ruff check .` exit 0 | ✅ | `ruff check .` → `All checks passed!` |
| 13 | No dangerous maturity overclaims in README/docs | No overclaims such as “ready for production”, “stable-for-public”, or “autonomous-by-default” | ✅ | `python scripts/private_beta_gate.py --json` → `dangerous_claim` blockers empty |

## P1 — Should be true before inviting testers

| # | Gate | Expected | Status | Proof / command |
|---|------|----------|--------|-----------------|
| 14 | Gate tests pass | 802/802 green | ⏳ | `bash scripts/ci/local_tests_only.sh` or manual gate subset |
| 15 | Windows test failures documented | Known failures isolated | ✅ | See docs/KNOWN_LIMITATIONS.md §“Windows test suite” |
| 16 | `scripts/activate_si_v3.sh` warns about beta | Header / guard added | ⏳ | Check script header |
| 17 | `README.md` does not claim production grade | Honest framing | ⏳ | Manual review + gate |
| 18 | API docs disabled by default in production | `ENABLE_API_DOCS=0` in `.env.production.example` | ✅ | File review |
| 19 | Rate limiting configured | `api/rate_limiter.py` wired + fallback in-memory | ✅ | Code review / docs/API_REFERENCE.md |
| 20 | Prometheus `/metrics` protected by middleware | `is_public_path('/metrics') == False` | ✅ | Verified in gate |

## P2 — Nice to have before inviting testers

- Separate OpenAPI schemas per API version.
- `modules_v3.py` shadowing fix (docs/API_VERSIONING.md audit finding #1).
- React frontend / React Native mobile API surface documented as secondary/unsupported.
- Outdated dependency bumps deferred to dedicated PRs (fastapi, cryptography, pytest).

## How to update this checklist

1. Run the proof command for the gate you want to toggle.
2. Paste the output (or a stable excerpt) into the “Proof / command” column.
3. Change the Status emoji only when you have fresh evidence.
4. Run `python scripts/private_beta_gate.py --json` before each commit to this file.

## Legend

- ✅ = verified with evidence in this branch
- ⏳ = pending / needs evidence
- ❌ = known failure, documented blocker
