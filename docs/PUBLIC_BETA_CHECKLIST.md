# Public Beta Checklist

## Status

- CI smoke enforced on PR: done
- Provider-dependent runtime required for this gate: no
- Automatic router changes: not done

## Enforced checks

- `ruff check .`
- `python scripts/smoke_e2e_cycle.py --fixture sha256 --skip-bea-eval --json`
- `python scripts/bea_eval.py --json`
- `python scripts/validate_local.py --quick`

## Observability

- [x] Redactor (`core/observability/redactor.py`) — secrets never in logs
- [x] MissionEvent (`core/observability/mission_event.py`) — lightweight structured event
- [x] Mission status report (`scripts/mission_status_report.py --json`)
- [x] 26 observability tests (redactor + MissionEvent + report logic)
- [x] No external telemetry (no Sentry, OTEL, Datadog, Prometheus)

## Still pending

- APK CI hardening
- v1 deprecation cleanup in the client
- public clean seed verification if a fresh seed is needed

## Notes

- The PR smoke workflow must stay fixture-backed.
- No OpenRouter key, Ollama daemon, or other secret is required.
- If a provider-backed test is needed, keep it outside PR smoke and run it
  separately as an opt-in gate.
