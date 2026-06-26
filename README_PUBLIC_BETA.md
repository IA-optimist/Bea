# Bea - Developer Preview / Private Beta 0.1

PUBLIC_BETA_READY: false

This repository is not ready for an open beta. The current target is a
supervised Private Beta 0.1 for 5-10 technical testers only.

## What Is Proved

| Area | Current evidence |
|---|---|
| Local validation | `python scripts/validate_local.py --quick` passed on 2026-06-26 |
| Python lint | `ruff check .` passed on 2026-06-26 |
| Flutter client API usage | `python scripts/check_client_v1_usage.py` passed: 0 active `/api/v1` calls under `beamax_app/lib` |
| Principal binding | `python scripts/check_policy_principal_binding.py` passed: 24 audited call sites, 0 unresolved gaps |
| Mission ID propagation | `python scripts/check_tool_executor_mission_id.py` passed: 6 audited call sites, 0 unresolved gaps |
| Public memory seed | `python scripts/seed_bea_memory.py --report --profile public` passed: 8 items checked, public safe |
| PR smoke workflow | `.github/workflows/pr-smoke.yml` exists and runs on `pull_request` |
| Rate-limiting | Rate-limiting intégré via `BEA_RATE_LIMIT_PER_MINUTE` / slowapi; do not expose the API without supervised network controls |

## Partially Validated

| Area | Status |
|---|---|
| Android APK | Launch and connectivity were previously validated on a physical Pixel 7. Mission UI and offline/network-failure behavior remain HUMAN_REQUIRED. |
| Qdrant live memory | Privacy scan ran on 2026-06-26 and found 1 private item in the live store. Cleanup is HUMAN_REQUIRED before any wider release. |
| Session storage | `RedisSessionStore` is the required/recommended backend for multi-process or multi-worker use. `InMemorySessionStore` is acceptable only for local single-process testing. |
| API versioning | Active Flutter `/api/v1` calls are 0 by script. Server-side v1 compatibility can remain only as a rollback surface until removal is deliberately validated. |

## Experimental Or Out Of Scope

- Self-improvement must stay disabled by default.
- Dangerous actions must remain gated or out of scope.
- HexStrike, business automation, multimodal, voice, browser automation, venture workflows, and SaaS deployment are experimental or partial unless a current gate proves otherwise.
- Testers must not use real secrets, private data, medical data, financial data, or customer data.

## Human Required

- HUMAN_REQUIRED: rotate any historical or shared secrets if rotation has not been proved outside the repo.
- HUMAN_REQUIRED: clean the Qdrant live store item detected by the privacy scan.
- HUMAN_REQUIRED: validate Android mission UI and offline/network-failure behavior on a physical device.
- HUMAN_REQUIRED: issue per-tester tokens without committing them.
- HUMAN_REQUIRED: use `RedisSessionStore` before multi-process or multi-worker testing.

## Recommendation

Private Beta 0.1 can proceed only for 5-10 technical testers under direct
supervision after the HUMAN_REQUIRED items are accepted and tracked.
Public beta remains NO-GO.
