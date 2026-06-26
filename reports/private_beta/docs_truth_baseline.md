# Docs Truth Baseline

Commit SHA de depart: `a59b034ad93c0ff71ed1b6692eb6d045a782b3c8`

## Docs Inspectees

- `README.md`
- `README_PUBLIC_BETA.md`
- `PUBLIC_BETA_CHECKLIST.md`
- `RELEASE_NOTES.md`
- `VERSION`
- `docs/STATUS.md`
- `docs/ALPHA_READINESS.md`
- `docs/API_VERSIONING.md`
- `docs/APK_PHYSICAL_DEVICE_VALIDATION.md`
- `docs/PRIVATE_BETA_SCOPE.md`
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

## Contradictions Trouvees

- Public beta docs mixed Developer Preview wording with launch-style checklist
  claims.
- `PUBLIC_BETA_CHECKLIST.md` said PR smoke was unavailable, while
  `.github/workflows/pr-smoke.yml` exists and runs on pull requests.
- API docs and reports mixed old Flutter `/api/v1` assumptions with the current
  script result: 0 active calls.
- APK docs used stronger wording than the evidence supports; mission UI and
  offline/network-failure were not proved.
- Dependency notes claimed missing packages that are present in `requirements.txt`.
- Qdrant live memory was sometimes treated as acceptable despite a privacy scan
  finding 1 private item.
- Historical/shared secret rotation was not consistently marked HUMAN_REQUIRED.
- `scripts/private_beta_gate.py` was referenced as a live gate, but the script is
  absent on the current commit.

## Dangerous Claims Found

- Release-hardening claims exceeded the current evidence in several docs.
- Checklist items were checked without current command proof.
- Android validation wording implied more coverage than launch/connectivity.
- Memory wording risked hiding the live Qdrant cleanup requirement.

## Checklist Items Douteux

- Android device validation.
- PR smoke unavailable claim vs present workflow.
- Dependency missing claims.
- Qdrant privacy status.
- Historical/shared secret status.
- Full test result during the docs truth loop.

## Elements Prouves

- `git rev-parse HEAD`: `a59b034ad93c0ff71ed1b6692eb6d045a782b3c8`
- `python scripts/validate_local.py --quick`: PASS.
- `python scripts/check_client_v1_usage.py`: PASS, 0 active `/api/v1` calls.
- `python scripts/check_policy_principal_binding.py`: PASS.
- `python scripts/check_tool_executor_mission_id.py`: PASS.
- `python scripts/seed_bea_memory.py --report --profile public`: PASS.
- `ruff check .`: PASS.
- `.github/workflows/pr-smoke.yml`: present and configured for `pull_request`.
- `.github/workflows/flutter_apk.yml`: present, partial PR gate plus release path.

## Elements Non Prouves

- Public beta readiness.
- Qdrant live memory cleanup.
- Historical/shared secret rotation.
- Android mission UI.
- Android offline/network-failure behavior.
- Full `pytest -q` result in the initial loop.
- `scripts/private_beta_gate.py --json`, because the script is absent.

## HUMAN_REQUIRED

- HUMAN_REQUIRED: rotate historical/shared secrets if not already proved outside
  the repo.
- HUMAN_REQUIRED: clean Qdrant live memory item `ecdaea85-db3`.
- HUMAN_REQUIRED: validate Android mission UI on a physical device.
- HUMAN_REQUIRED: validate Android offline/network-failure behavior.
- HUMAN_REQUIRED: create per-tester tokens and keep them out of git.
- HUMAN_REQUIRED: use `RedisSessionStore` for multi-process or multi-worker use.

## Recommandation Initiale

Private Beta 0.1 can be considered only for 5-10 technical testers under
supervision. Public beta remains NO-GO.
