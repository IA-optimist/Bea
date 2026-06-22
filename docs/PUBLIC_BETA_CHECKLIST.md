# Public Beta Checklist

PUBLIC_BETA_READY: false

This file mirrors the root [PUBLIC_BETA_CHECKLIST.md](../PUBLIC_BETA_CHECKLIST.md).

## Required Before Open Beta

- [ ] Qdrant live privacy scan proves 0 private items.
- [ ] Historical/shared secret rotation is proved by the owner.
- [ ] Android mission UI is validated on a physical device.
- [ ] Android offline/network-failure behavior is validated on a physical
  device.
- [ ] `RedisSessionStore` is configured for multi-process or multi-worker use.
- [ ] Full validation and docs truth gate pass.
- [ ] No current docs claim more than the evidence proves.

## Observability

- [x] Redactor (`core/observability/redactor.py`) — secrets never in logs
- [x] MissionEvent (`core/observability/mission_event.py`) — lightweight structured event
- [x] Mission status report (`scripts/mission_status_report.py --json`)
- [x] 26 observability tests (redactor + MissionEvent + report logic)
- [x] No external telemetry (no Sentry, OTEL, Datadog, Prometheus)

## Current Private Beta Position

Private Beta 0.1 can be considered only for 5-10 technical testers under
supervision.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: Qdrant cleanup proof.
- HUMAN_REQUIRED: secret rotation proof.
- HUMAN_REQUIRED: Android physical-device proof.
