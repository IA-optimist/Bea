# Béa 0.1.0-dev-preview — Developer Preview Release Notes

**Status: Developer Preview (limited)**
Not production-ready. Not stable. APIs may change without notice.
Data may be lost on breaking updates.

---

## What's included

### Core pipeline

- Multi-agent execution: forge-builder (code), scout-research (analysis), shadow-advisor (JSON advisory)
- OpenRouter as primary provider (gpt-oss-120b:free / gpt-oss-20b:free), Ollama as local fallback (gemma4:12b)
- Provider/model tracked through pipeline and stored in `workspace/learning_runs.json`

### API hardening

- CORS: configurable via `BEA_CORS_ORIGINS` — wildcard blocked with `allow_credentials=True`
- Rate-limiting: slowapi, 60 req/min default, `BEA_RATE_LIMIT_ENABLED` / `BEA_RATE_LIMIT_PER_MINUTE`

### Observability

- Privacy-safe: prompts and secrets never in logs (`core/observability/redactor.py`)
- MissionEvent: 13 fields (mission_id, provider_used, model_used, duration_ms, error_category...)
- `scripts/mission_status_report.py --json`: local summary from learning_runs.json

### Benchmarks

- 3-role real benchmark: forge-builder (OpenRouter 1.0 / Ollama 0.0), scout-research (both 1.0), shadow-advisor (OpenRouter 1.0 / Ollama 0.33)
- Advisory routing: OpenRouter recommended for all 3 roles (low confidence, non-enforced)

### Flutter / Mobile

- beamax_app uses `/api/v3` exclusively (0 active `/api/v1` calls confirmed)
- APK CI workflow: gate + `workflow_dispatch` build
- v1 server endpoints preserved for rollback until 2026-10-01

---

## Validation commands

```bash
python scripts/validate_local.py --quick
python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json
python scripts/bea_eval.py --json
python scripts/release_check.py --json
```

## Known gaps before Public Beta stable

1. APK v3 validated on physical device
2. CI GitHub Actions enforced on PR (currently `workflow_dispatch` only)
3. MissionEvent wired into pipeline_auto executor (currently building block only)
4. model_used reflects sent model, not provider-resolved model

## Rollback

v1 server endpoints are preserved. If the Flutter APK has issues, the previous
APK (using /api/v1) can be reinstalled — the server will respond correctly.

## Do not use in production

- No audit of multi-tenant isolation
- No formal security review completed
- No SLA or uptime guarantee
- Self-improvement daemon (`BEA_CONTINUOUS_IMPROVEMENT`) requires human supervision
