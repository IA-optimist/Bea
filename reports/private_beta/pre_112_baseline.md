# Pre-#112 Baseline

Generated: 2026-06-26
main commit before rebase: `924c0f68a25b8de9d3bb6464876f1a166ed4cbd5`

## PR #116

- Status: MERGED 2026-06-26T16:09:19Z
- Action: Merged before #112 rebase to ensure docs truth is on main

## PR #112 State (before rebase)

- Title: fix(eval): stabilize bea_eval and enforce completion truth gates
- Branch: claude/stabilize-bea-eval-and-completion-truth-gates
- Mergeable: CONFLICTING (merge conflict with main)
- Draft: false
- CI: Multiple failures (expected — caused by conflict state, not by code)
  - PASS: Gitleaks, Kernel Architecture Validation, CodeQL, security-strict-mypy, pip-audit, Windows portability, Analyze (actions/python/js)
  - FAIL: pr-smoke, security, detect-secrets, unit (ubuntu+windows), test, bandit, mypy-delta

## Files Touched by #112

- `.github/workflows/pr-smoke.yml` — adds `--isolated` flag to bea_eval CI step
- `core/coding_agent/artifact_validator.py` — adds `.valid`/`.reason` aliases + `validate_coding_report()` wrapper
- `core/evals/bea_eval.py` — fixes `eval_repo_map_tests` target file (warm-store dependency)
- `docs/ALPHA_READINESS.md` — documents --isolated mode
- `docs/E2E_CYCLE.md` — documents completion truth gate + bea_eval isolated mode
- `docs/PUBLIC_BETA_CHECKLIST.md` — marks two new gates as checked
- `scripts/bea_eval.py` — adds `--isolated` flag (temp SQLite store, no global pollution)
- `tests/core/evals/test_bea_eval_isolated.py` — isolated eval test
- `tests/test_false_completed_regression.py` — completion truth regression tests

## Known Conflicts

Both #116 and #112 touch:
- `docs/ALPHA_READINESS.md`
- `docs/PUBLIC_BETA_CHECKLIST.md`

Conflict resolution strategy:
- Keep #116 version for truth/framing (PUBLIC_BETA_READY: false, HUMAN_REQUIRED items)
- Merge #112 additions (--isolated gate, completion truth gate markers)
- Do NOT remove any HUMAN_REQUIRED items
- Do NOT remove PUBLIC_BETA_READY: false

## Tests to Run After Rebase

1. `python scripts/validate_local.py --quick`
2. `ruff check .`
3. `pytest tests/test_false_completed_regression.py -q`
4. `pytest tests/core/evals/test_bea_eval_isolated.py -q`
5. `python scripts/bea_eval.py --json --isolated`
6. `python scripts/check_docs_truth.py`
7. `pytest -q` (full suite)

## Risks

- Conflict in docs files — must not reduce truth fidelity from #116
- `--isolated` mode adds temp SQLite store: verify no leftover temp files
- `validate_coding_report()` wrapper: verify it doesn't weaken existing checks

## Initial Decision

PROCEED — high P1 value, rebase expected to be clean for code files; docs conflict resolvable.
