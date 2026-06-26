# Android APK Physical Device Validation

Current status: partially validated.

The APK must not be described as complete. The current evidence supports
launch/connectivity only. Mission UI and offline/network-failure behavior remain
HUMAN_REQUIRED.

## Evidence Currently Accepted

| Area | Status | Notes |
|---|---:|---|
| Physical install | PARTIAL | Prior Pixel 7 session reported install and launch |
| API connectivity | PARTIAL | Prior session reported `/health` and `/api/v3/missions` connectivity |
| Active Flutter `/api/v1` calls | PASS | `python scripts/check_client_v1_usage.py` reports 0 active calls |
| Tokens in logcat | PARTIAL | Prior session reported no token in logcat; repeat before wider testing |

## Not Yet Proved

- HUMAN_REQUIRED: submit a mission from the Android mission UI and capture the result.
- HUMAN_REQUIRED: test API unavailable at launch.
- HUMAN_REQUIRED: test API loss during an active mission.
- HUMAN_REQUIRED: test token rejection/expired-token behavior.
- HUMAN_REQUIRED: record device, Android version, APK SHA, backend commit, and
  date for the next run.

## Validation Checklist

- [ ] APK installs on a physical device.
- [ ] App launches without crash.
- [ ] API host configuration is visible to the tester/operator.
- [ ] `/health` succeeds.
- [ ] `/api/v3/missions` succeeds.
- [ ] Mission is submitted through the UI.
- [ ] Mission result or failure state is visible in the UI.
- [ ] Offline startup behavior is understandable.
- [ ] Network loss during a mission is handled without data loss.
- [ ] No token or private data appears in logs.

## Status For Private Beta 0.1

Android can be offered only as an experimental companion surface. Testers must
be able to use the API directly if the APK fails.
