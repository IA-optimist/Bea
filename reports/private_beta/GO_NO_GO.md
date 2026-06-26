# Private Beta 0.1 Go / No-Go

PRIVATE_BETA_READY: true
PUBLIC_BETA_READY: false

Verdict: conditional GO for 5-10 technical testers under supervision. NO-GO for
public beta.

## Evidence Used

| Command or file | Result |
|---|---|
| `git rev-parse HEAD` | `924c0f68a25b8de9d3bb6464876f1a166ed4cbd5` |
| `python scripts/validate_local.py --quick` | PASS |
| `python scripts/private_beta_gate.py --json` | PASS, wrapper docs/v1/quick validation; human-required items preserved |
| `python scripts/check_client_v1_usage.py` | PASS, 0 active `/api/v1` calls under `beamax_app/lib` |
| `python scripts/check_policy_principal_binding.py` | PASS, 24 call sites audited |
| `python scripts/check_tool_executor_mission_id.py` | PASS, 6 call sites audited |
| `python scripts/seed_bea_memory.py --report --profile public` | PASS, public seed safe |
| `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` | WARNING, 1 private item in live store |
| `ruff check .` | PASS |
| `.github/workflows/pr-smoke.yml` | Present and configured for `pull_request` |
| `.github/workflows/flutter_apk.yml` | Present; PR check is partial and release build needs release/workflow context |

## Current Blockers For Public Beta

- Qdrant live memory is cleanup required: item `ecdaea85-db3` was detected as
  private by the privacy scan.
- Historical/shared secret rotation is not proved by repo evidence.
- Android mission UI is not proved.
- Android offline/network-failure behavior is not proved.
- Full `pytest -q` was not completed during the initial docs truth command loop.
- `scripts/private_beta_gate.py --json` now exists as a wrapper. It does not
  mark Qdrant cleanup, historical/shared secret rotation, or Android mission UI
  as resolved.

## Private Beta Conditions

- Testers must be technical and supervised.
- Testers must not use real secrets, private data, medical data, financial data,
  customer data, or other sensitive real data.
- Self-improvement must remain disabled by default.
- Dangerous actions must be gated or kept out of scope.
- Multi-process or multi-worker use must use `RedisSessionStore`.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate historical/shared secrets if rotation has not been
  proved outside the repo.
- HUMAN_REQUIRED: clean Qdrant live memory before any wider release.
- HUMAN_REQUIRED: validate Android mission UI on a physical device.
- HUMAN_REQUIRED: validate Android offline/network-failure behavior on a
  physical device.
- HUMAN_REQUIRED: create per-tester tokens and keep them out of git.
