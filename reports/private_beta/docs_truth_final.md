# Docs Truth Final

PRIVATE_BETA_READY: true
PUBLIC_BETA_READY: false
DOCS_TRUTH_SYNC: true
HUMAN_REQUIRED:

* HUMAN_REQUIRED: rotate historical/shared secrets if not already proved outside the repo.
* HUMAN_REQUIRED: clean Qdrant live memory item `ecdaea85-db3`.
* HUMAN_REQUIRED: validate Android mission UI on a physical device.
* HUMAN_REQUIRED: validate Android offline/network-failure behavior.
* HUMAN_REQUIRED: create per-tester tokens and keep them out of git.
* HUMAN_REQUIRED: use `RedisSessionStore` for multi-process or multi-worker use.

This final report covers the Developer Preview / Private Beta 0.1 truth sync.

## Commit SHA Final

Docs truth sync commit: `e974ee14c04cedaa820a813de3f4b24d833f8b8f`.

Note: a commit cannot contain its own final hash without changing that hash. The
branch tip is available from Git and the PR metadata.

## Fichiers Modifies

- `README.md`
- `README_PUBLIC_BETA.md`
- `PUBLIC_BETA_CHECKLIST.md`
- `RELEASE_NOTES.md`
- `docs/STATUS.md`
- `docs/ALPHA_READINESS.md`
- `docs/API_VERSIONING.md`
- `docs/APK_PHYSICAL_DEVICE_VALIDATION.md`
- `docs/PRIVATE_BETA_SCOPE.md`
- `docs/PRIVATE_BETA_RUNBOOK.md`
- `docs/TESTER_QUICKSTART.md`
- `docs/TESTER_SAFETY_RULES.md`
- `docs/BETA_ACCESS_SETUP.md`
- `docs/BETA_INCIDENT_RUNBOOK.md`
- `docs/BETA_TESTER_GUIDE.md`
- `docs/FEEDBACK_GUIDE.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/PRIVACY_FOR_TESTERS.md`
- `docs/TROUBLESHOOTING.md`
- `reports/private_beta/GO_NO_GO.md`
- `reports/private_beta/private_beta_gate_result.md`
- `reports/private_beta/private_beta_gate_result.json`
- `reports/private_beta/docs_truth_baseline.md`
- `reports/private_beta/docs_truth_final.md`
- `scripts/check_docs_truth.py`
- `tests/test_docs_truth.py`

## Contradictions Corrigees

- Flutter active `/api/v1` status now follows `check_client_v1_usage.py`.
- Android APK status now says partial validation only.
- Qdrant live memory now says cleanup required.
- Historical/shared secret rotation remains HUMAN_REQUIRED.
- PR smoke docs now match `.github/workflows/pr-smoke.yml`.
- Dependency claims were removed and replaced by current `requirements.txt`
  evidence.
- Missing `scripts/private_beta_gate.py` is documented as a failed command.

## Contradictions Restantes

No critical contradiction remains in the active truth-sync docs after the docs
gate passes. Historical/archive docs are not the source of record.

## Commandes Lancees

| Command | Result |
|---|---|
| `git rev-parse HEAD` | `a59b034ad93c0ff71ed1b6692eb6d045a782b3c8` |
| `python scripts/private_beta_gate.py --json` | FAIL: script absent |
| `python scripts/validate_local.py --quick` | PASS |
| `python scripts/check_client_v1_usage.py` | PASS |
| `python scripts/check_policy_principal_binding.py` | PASS |
| `python scripts/check_tool_executor_mission_id.py` | PASS |
| `python scripts/seed_bea_memory.py --report --profile public` | PASS |
| `python scripts/audit_memory_store.py --dry-run --privacy-scan --json` | WARNING: 1 private live item |
| `ruff check .` | PASS |
| `python scripts/check_docs_truth.py` | PASS |
| `pytest tests/test_docs_truth.py tests/test_public_beta_docs_consistency.py -q` | PASS, 8 passed |
| `pytest -q` | FAIL, 7 failed / 6080 passed / 766 skipped / 6 xfailed |

## Statuts Reels

- APK: partially validated; mission UI and offline/network-failure are
  HUMAN_REQUIRED.
- Qdrant: cleanup required because the live privacy scan found 1 private item.
- Historical/shared secrets: HUMAN_REQUIRED unless rotation is proved by the
  owner outside the repo.
- CI: `ci.yml`, `pr-smoke.yml`, and `flutter_apk.yml` exist; branch result still
  depends on GitHub execution.
- Private beta: conditional GO for 5-10 technical testers under supervision.
- Public beta: NO-GO.

## Full Pytest Residual Failures

The final `pytest -q` run completed in about 9 minutes and failed in areas
outside the docs truth gate:

- `tests/test_rate_limit_config.py`: 4 failures because
  `api.rate_limit_middleware` does not expose `RATE_LIMIT_ENABLED` and does not
  raise the expected runtime error in the tested scenario.
- `tests/test_sprint3_agent_coder.py`: 2 failures because repo-map ranking
  returns `RepoMapService.build` before `build_repo_map`; the SWE-lite wrapper
  fails from that case.
- `tests/test_stabilization_final.py`: 1 failure because root Markdown docs
  exist (`README_PUBLIC_BETA.md`, `PUBLIC_BETA_CHECKLIST.md`, `RELEASE_NOTES.md`,
  and pre-existing root docs). These files are required by the current docs truth
  mission and were not removed.
