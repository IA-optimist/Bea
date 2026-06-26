# Bea Status

Last truth sync baseline: 2026-06-26, commit
`a59b034ad93c0ff71ed1b6692eb6d045a782b3c8`.

PRIVATE_BETA_READY: true for 5-10 technical testers under supervision.
PUBLIC_BETA_READY: false.

Bea is a Developer Preview / Private Beta 0.1. This document is the source of
record for active component status. Older reports can be useful history, but
they do not override this page.

## Current Verdict

| Question | Answer |
|---|---|
| Private beta for supervised technical testers? | Conditional GO |
| Open beta? | NO-GO |
| Can testers use real secrets or sensitive real data? | No |
| Can dangerous actions run without gates? | No |
| Is self-improvement enabled by default? | No |

## Proved

| Area | Evidence |
|---|---|
| Quick local gate | `python scripts/validate_local.py --quick` passed on 2026-06-26 |
| Lint | `ruff check .` passed on 2026-06-26 |
| Flutter active v1 usage | `python scripts/check_client_v1_usage.py` passed: 0 active `/api/v1` calls |
| Principal binding | `python scripts/check_policy_principal_binding.py` passed: 24 call sites audited, 0 unresolved gaps |
| Mission ID propagation | `python scripts/check_tool_executor_mission_id.py` passed: 6 call sites audited, 0 unresolved gaps |
| Public memory seed | `python scripts/seed_bea_memory.py --report --profile public` passed: public-safe seed |
| PR smoke | `.github/workflows/pr-smoke.yml` exists and runs on pull requests |
| Dependencies | `requirements.txt` contains FastAPI, pytest, psutil, structlog, langchain packages, Redis, Qdrant client, and slowapi |

## Partially Validated

| Area | Status |
|---|---|
| Core agentic runtime | Advanced and covered by local gates, but still Developer Preview |
| Auth/principal binding | Advanced, checked by script and tests |
| Policy gates | Advanced, checked by local validation and focused scripts |
| Mission ID propagation | Advanced, checked by script |
| Android mobile | Launch/connectivity previously validated; mission UI and offline/network-failure remain HUMAN_REQUIRED |
| Qdrant live memory | Scan ran and found 1 private live item; cleanup required |
| CI | Workflows exist for main CI, PR smoke, and Flutter APK; branch result still depends on GitHub execution |

## Experimental Or Partial

- HexStrike and offensive/cyber workflows are out of Private Beta 0.1 scope.
- Business automation, venture workflows, SaaS deployment, browser automation,
  voice, and multimodal features are experimental or partial unless a current
  validation report proves a narrower claim.
- Self-improvement is disabled by default and must stay opt-in with operator
  review.

## Runtime Boundaries

| Component | Current truth |
|---|---|
| `RedisSessionStore` | Required/recommended for multi-process or multi-worker testing |
| `InMemorySessionStore` | Acceptable only for local single-process testing |
| Dangerous tool execution | Must be gated or out of scope |
| Real sensitive data | Not allowed for testers |
| API v1 | Server compatibility may remain, but active Flutter `/api/v1` calls are 0 by script |

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate historical/shared secrets if rotation is not proved
  outside the repo.
- HUMAN_REQUIRED: clean Qdrant live memory item `ecdaea85-db3` detected by the
  privacy scan.
- HUMAN_REQUIRED: validate Android mission UI on a physical device.
- HUMAN_REQUIRED: validate Android offline/network-failure behavior on a
  physical device.
- HUMAN_REQUIRED: issue per-tester tokens without committing them.
- HUMAN_REQUIRED: configure `RedisSessionStore` before multi-process or
  multi-worker testing.
