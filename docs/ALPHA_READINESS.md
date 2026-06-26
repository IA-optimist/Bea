# Alpha Readiness

This page is retained as historical context for the transition into Developer
Preview / Private Beta 0.1. Current status is controlled by
[STATUS.md](STATUS.md).

PUBLIC_BETA_READY: false

## Current Alpha-To-Private-Beta Position

| Area | Status |
|---|---|
| Core mission runtime | Advanced, covered by quick validation and focused checks |
| Auth principal binding | Advanced, `check_policy_principal_binding.py` passes |
| Mission ID propagation | Advanced, `check_tool_executor_mission_id.py` passes |
| Flutter active `/api/v1` calls | 0 active calls by `check_client_v1_usage.py` |
| Android APK | Partially validated; mission UI and offline/network-failure are HUMAN_REQUIRED |
| Qdrant live memory | Cleanup required; privacy scan found 1 private item |
| Public beta | NO-GO |

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate historical/shared secrets if not already proved.
- HUMAN_REQUIRED: clean Qdrant live memory.
- HUMAN_REQUIRED: complete Android mission UI and offline/network-failure tests.
- HUMAN_REQUIRED: use `RedisSessionStore` for multi-process or multi-worker use.
