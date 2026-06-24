# Béa — Known Limitations (Private Beta)

> Last updated: 2026-06-24 on branch `beta/private-readiness-kilo-kimi`.

This document lists what Béa cannot yet do reliably. It exists so testers expectations are honest.

## System maturity

- Béa is a **private beta / developer preview / experimental** system.
- The cognitive core (mission lifecycle, kernel, auth middleware) is the most mature part.
- Many other surfaces are scaffolding, stubs, or partial wiring.

## Frontend / mobile

- **React frontend (`frontend/`)**: backend integration is broken. It calls `/api/v2/system/status` and `/api/v2/products/deploy`, which do not exist. It is **not** supported for testers.
- **React Native mobile (`mobile/`)**: scaffolding only. Not supported for testers.
- **Flutter app (`jarvismax_app/`)**: canonical mobile target, but treat it as experimental for the beta.

## API versions

- **v1 routes** are deprecated and will sunset on 2026-10-01. They are kept only because the Flutter app still uses `/api/v1/missions/{id}/stream`.
- **v2 routes** are the current stable product surface.
- **v3 routes** are the preferred surface but still evolving.
- OpenAPI `/docs` mixes v1/v2/v3 unless `ENABLE_API_DOCS=0` disables it.

## Business handlers

| Mission | Status |
|---------|--------|
| `business.scan_opportunities` | Real calls to public APIs (Product Hunt, Reddit, HN). |
| `business.optimize_taxes` | Real France tax calculation. |
| `business.check_compliance` | Regex blacklist/greylist. |
| `business.build_product` | Generates a static HTML template only. |
| `business.deploy_product` | TODO — no real deployment. |
| `business.track_revenue` | Dataclasses only — no Stripe integration. |

## Security / ops

- HexStrike v2 refactor is ~5% complete; imports may fail if `psutil` is missing.
- `api/routes/extensions.py`, `metrics_mobile.py`, `venture.py` have documented auth gaps in `docs/STATUS.md` (HIGH). They are gated where possible, but not fully hardened.
- Docker container still runs as root.
- The full Windows test suite has known failures (path separators, `grep` subprocess, file locking, encoding). CI primarily targets Linux.

## CI / test

- `ruff check .` passes.
- Full pytest has ~33 failures on Windows in this branch (many environment-specific). The Linux gate tests are the blocking suite.
- Coverage gate is 55%.

## Self-improvement

- Disabled by default for the private beta.
- Activating it requires explicit operator approval.
- `BEA_SKIP_IMPROVEMENT_GATE` must never be set.

## LLM behavior

- Output quality depends heavily on the model.
- Local Ollama models are slower and may hallucinate more.
- Long missions may time out or get stuck in retry loops.

## Data

- Memory features require Qdrant (or fall back to local SQLite/JSONL).
- There is no migration path guaranteed between beta versions.

## What to do when you hit a limitation

1. Check this file.
2. If it is not listed here, open a bug report using the template.
3. If it is listed here but blocks your testing, open a beta-feedback issue describing your use case.
