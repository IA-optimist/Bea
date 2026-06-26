# Release Notes - Private Beta 0.1 Truth Sync

PUBLIC_BETA_READY: false

This release note describes the current Developer Preview / Private Beta 0.1
state. It does not announce an open beta.

## Validated In This Sync

- `python scripts/validate_local.py --quick` passed.
- `ruff check .` passed.
- `python scripts/check_client_v1_usage.py` passed with 0 active Flutter
  `/api/v1` calls.
- `python scripts/check_policy_principal_binding.py` passed.
- `python scripts/check_tool_executor_mission_id.py` passed.
- `python scripts/seed_bea_memory.py --report --profile public` passed.
- `.github/workflows/pr-smoke.yml` exists and runs on pull requests.

## Partial Or Human-Gated

- Android APK: launch/connectivity evidence exists, but mission UI and
  offline/network-failure testing remain HUMAN_REQUIRED.
- Qdrant live memory: privacy scan found 1 private item, so cleanup is
  HUMAN_REQUIRED.
- Historical/shared secrets: rotation is HUMAN_REQUIRED unless the owner has
  proof outside the repository.
- `scripts/private_beta_gate.py --json`: failed on this branch because the script
  is absent from the current commit.
- Full `pytest -q`: the initial docs truth command loop timed out before a full
  result was produced.

## Scope

Private Beta 0.1 is only for 5-10 technical testers under supervision. Testers
must use toy data and must not use real secrets or sensitive real data.
