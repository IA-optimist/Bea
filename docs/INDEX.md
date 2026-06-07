# Documentation Index

## Living documents (kept up-to-date)

| Doc | Purpose |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System architecture overview |
| [`API_REFERENCE.md`](API_REFERENCE.md) | REST API endpoints |
| [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) | Production deployment |
| [`QUICKSTART.md`](QUICKSTART.md) | Dev environment setup |
| [`SECURITY_AUDIT.md`](SECURITY_AUDIT.md) | Running security posture (updated each audit session) |
| [`STATUS.md`](STATUS.md) | Current project status |
| [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) | Go/no-go production checklist |
| [`NOTIFICATIONS_SYSTEM.md`](NOTIFICATIONS_SYSTEM.md) | Alert/notification subsystem |
| [`REALTIME_DASHBOARD.md`](REALTIME_DASHBOARD.md) | WebSocket metrics dashboard |
| [`ROUTER_USAGE_MAP.md`](ROUTER_USAGE_MAP.md) | LLM router routing map |
| [`kernel_spec.md`](kernel_spec.md) | Kernel contract spec |
| [`API_VERSIONING.md`](API_VERSIONING.md) | v1 / v2 / v3 surface map + sunset plan |
| [`AUDIT_ROADMAP.md`](AUDIT_ROADMAP.md) | Phase-by-phase audit progress + remaining debt |
| [`AUTONOMY.md`](AUTONOMY.md) | Autonomy daemon + skills + REST API operator guide |

## Operational scripts

Located in `scripts/` (at repo root):

- `scripts/rotate_secrets.sh` — interactive secret rotation on VPS1
- `scripts/verify_prod.sh` — read-only prod diagnostic
- `scripts/migrate_to_nonroot.sh` — container UID=1000 migration

## CI / Workflows

Located in `.github/workflows/`:

- `ci.yml` — Python tests + ruff lint (blocking) + coverage (≥45%) + Docker build
- `flutter_apk.yml` — APK build on tag `v*` or manual dispatch
- `pre-commit.yml` — detect-secrets + gitleaks on every push
- `kernel_ci.yml` — kernel contract tests
- `unit.yml`, `deploy.yml` — unit + deploy pipelines

## Archive

Historical session reports, completed consolidation plans, and deprecated
designs are in [`archive/`](archive/). They're kept for traceability but
aren't maintained.

## Other documentation

- `README.md` (repo root) — project overview + install
- `CHANGELOG.md` (repo root) — release notes
- Per-module `README.md` in `agents/`, `business/`, `monitoring/`, `mcp/`,
  etc. — module-specific docs
- `beamax_app/BUILD_INSTRUCTIONS.md` — Flutter app build
