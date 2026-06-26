# Bea - Public Beta Checklist

PUBLIC_BETA_READY: false

This checklist tracks what blocks an open beta. It is not a launch checklist.
Checked items require a command, workflow, or file-level proof.

## Current Recommendation

| Decision | Value |
|---|---|
| Release label | Developer Preview / Private Beta 0.1 |
| Private beta | Conditional GO for 5-10 technical testers under supervision |
| Public beta | NO-GO |
| Documentation truth sync | In progress on `docs/truth-sync-private-beta` |

## Proved By Current Checks

| Check | Status | Evidence |
|---|---:|---|
| Local validation quick gate | PASS | `python scripts/validate_local.py --quick`, 2026-06-26 |
| Ruff | PASS | `ruff check .`, 2026-06-26 |
| Flutter active `/api/v1` calls | PASS | `python scripts/check_client_v1_usage.py`: 0 active calls |
| Principal binding | PASS | `python scripts/check_policy_principal_binding.py`: 24 call sites audited |
| Mission ID propagation | PASS | `python scripts/check_tool_executor_mission_id.py`: 6 call sites audited |
| Public seed | PASS | `python scripts/seed_bea_memory.py --report --profile public`: 8 public-safe items |
| PR smoke workflow present | PASS | `.github/workflows/pr-smoke.yml` runs on `pull_request` |
| Flutter APK workflow present | PARTIAL | `.github/workflows/flutter_apk.yml` exists; PR path gates v1 usage and `flutter pub get`; release build needs workflow/tag context |

## Not Proved Or Blocked

| Item | Status | Required action |
|---|---:|---|
| Public beta | BLOCKED | Keep `PUBLIC_BETA_READY: false` |
| Qdrant live memory privacy | CLEANUP_REQUIRED | 2026-06-26 dry-run scan found 1 private live item |
| Historical secret rotation | HUMAN_REQUIRED | Rotation is not proved in repo evidence |
| Android mission UI | HUMAN_REQUIRED | Physical launch/connectivity is not enough |
| Android offline/network-failure behavior | HUMAN_REQUIRED | Must be tested on a device |
| Full `pytest -q` during truth sync | NOT COMPLETED | Initial command loop timed out before a result file was produced |
| `scripts/private_beta_gate.py --json` | FAILED | Script is absent on current `main` commit `a59b034` |
| Multi-worker session storage | HUMAN_REQUIRED | Use `RedisSessionStore`; `InMemorySessionStore` only for local single-process testing |

## Public Beta Exit Criteria

- [ ] Qdrant live memory privacy scan proves 0 private items.
- [ ] Historical/shared secrets are rotated by a human owner and recorded outside this repo.
- [ ] Android mission UI is validated on a physical device.
- [ ] Android offline and network-failure flows are validated on a physical device.
- [ ] `RedisSessionStore` is configured for multi-process or multi-worker use.
- [ ] Public tester guide explicitly forbids real secrets and sensitive real data.
- [ ] Full validation gate is green in CI for a PR.
- [ ] No open critical contradiction exists in the active docs.

## Private Beta 0.1 Scope

Private Beta 0.1 can be considered for 5-10 technical testers only when the
owner accepts the remaining HUMAN_REQUIRED work. Testers must use toy data and
must expect manual supervision.
