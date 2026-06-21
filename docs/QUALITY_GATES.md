# Quality Gates

Béa keeps historical debt visible without allowing it to grow silently. The
default local entrypoint is:

```powershell
python scripts\validate_local.py --quick
```

Use the full lane before pushing larger changes:

```powershell
python scripts\validate_local.py --full
```

## Blocking Gates

| Gate | Command | Policy |
|---|---|---|
| Ruff | `python -m ruff check .` | Blocking. Fix violations in the PR. |
| Critical pytest lane | `pytest -m "not quarantine" ...` via `validate_local.py` | Blocking for hardening and architecture tests. |
| Kernel import boundaries | `python scripts/check_kernel_import_boundaries.py` | Blocking. Kernel must not import forbidden layers. |
| Coverage threshold | `python scripts/check_coverage_threshold.py` | Blocking. CI coverage fail-under is currently 60 and may only ratchet upward. |
| Python wheel | `python -m build --wheel` | Blocking in full local validation when `build` is installed, and in CI. |

## Ratchet Gates

| Gate | Baseline | Rule |
|---|---|---|
| Mypy | `quality/mypy-baseline.json` | `scripts/check_mypy_baseline.py` fails if error count exceeds `max_errors`. |
| Bandit | `quality/bandit-baseline.json` | Fails if any Bandit test-id count exceeds baseline. |
| pip-audit | `quality/pip-audit-baseline.json` | Fails if a vulnerability ID is not acknowledged in the baseline. |
| Silent `except/pass` | `quality/silent-except-baseline.json` | Fails if `except: pass` or `except Exception: pass` handlers increase. |
| Test markers | `quality/test-marker-baseline.json` | Fails if `quarantine`, `xfail`, or `stale` marker counts increase. |
| Legacy silent swallows | `quality/legacy_silent_swallows.json` | Enforced by `tests/test_no_new_silent_swallows.py`; new `_silent_log.debug("suppressed_exception", ...)` sites are forbidden. |

Quarantined tests are run as a non-blocking signal in full local validation and
CI. Existing quarantine debt is tracked by the marker ratchet.

## Updating A Baseline

Baselines are not a way to make a PR pass. Update one only when:

1. The current count was measured from a clean branch.
2. The PR explains why the debt is temporarily accepted, or lowers the baseline
   after cleanup.
3. The corresponding command passes after the baseline change.

Examples:

```powershell
python scripts\check_silent_except_baseline.py --report-json quality\silent-except-report.json
python scripts\check_test_marker_baseline.py --report-json quality\test-marker-report.json
python -m mypy core api kernel --ignore-missing-imports --show-error-codes > mypy-report.txt
python scripts\check_mypy_baseline.py mypy-report.txt quality\mypy-baseline.json
```

Never lower the coverage threshold or raise a debt baseline just to pass a PR
without a written justification.
