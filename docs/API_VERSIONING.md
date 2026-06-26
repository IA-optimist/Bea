# API Versioning

Last checked: 2026-06-26.

## Current Truth

| Question | Answer |
|---|---|
| Does Flutter actively call `/api/v1`? | No, current script result is 0 active calls. |
| What proved that? | `python scripts/check_client_v1_usage.py` passed on 2026-06-26. |
| Can server-side v1 routes be removed automatically? | No. Removal needs a deliberate compatibility check and release plan. |
| Is public beta unblocked by API versioning alone? | No. `PUBLIC_BETA_READY: false`. |

## Evidence

`python scripts/check_client_v1_usage.py` reported:

```text
[OK] beamax_app\lib - 0 active /api/v1 calls (Flutter uses /api/v3)
```

This proves only the Flutter source tree checked by the script. It does not
prove that every old APK installed by a tester has been rebuilt and distributed.

## Policy

- New client code must use `/api/v2` or `/api/v3`.
- New Flutter `/api/v1` calls are not allowed.
- Existing server-side `/api/v1` routes may remain as rollback compatibility
  until removal is reviewed.
- Docs must not claim a server route is unused unless a script or telemetry
  proves it.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: confirm no tester is using an old APK before removing
  compatibility routes.
- HUMAN_REQUIRED: update release notes when compatibility routes are removed.
