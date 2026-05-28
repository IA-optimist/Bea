"""Delta gate for Bandit (Python static security scanner).

Audit follow-up: there is no automated check for dangerous Python patterns
(eval/exec/shell=True/etc.) — the initial audit found zero such patterns
but nothing prevents one from being introduced in a future PR.

Bandit catches them by default. To avoid the typical pitfall of "Bandit
floods CI with false positives on the first run", we use the same
delta-gate pattern as the mypy and pip-audit baselines:

  - The baseline ``quality/bandit-baseline.json`` lists per-test-id counts.
  - Existing files may keep their current count or lower it.
  - Any new test-id occurrence above the baseline fails CI.

Bandit JSON output has the shape::

    {"results": [{"test_id": "B102", "filename": "...", ...}, ...]}

We aggregate counts by ``test_id`` (e.g. B102 = exec_used, B602 =
subprocess_popen_with_shell_equals_true) and compare to the baseline.

Usage::

    bandit -r api core kernel -f json -o bandit.json --exit-zero
    python scripts/check_bandit_baseline.py bandit.json \\
        quality/bandit-baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _counts_by_test_id(report: dict) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for result in report.get("results", []):
        tid = result.get("test_id", "?")
        counts[tid] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bandit_json", type=Path,
                        help="JSON output from `bandit -f json`")
    parser.add_argument("baseline_json", type=Path,
                        help="quality/bandit-baseline.json")
    args = parser.parse_args(argv)

    if not args.bandit_json.exists():
        sys.stderr.write(f"bandit report not found: {args.bandit_json}\n")
        return 2
    if not args.baseline_json.exists():
        sys.stderr.write(
            f"baseline not found: {args.baseline_json}\n"
            "Create it with `{\"counts\": {}}` to start enforcing from scratch.\n"
        )
        return 2

    report = json.loads(args.bandit_json.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
    baseline_counts: dict[str, int] = baseline.get("counts", {})

    actual = _counts_by_test_id(report)

    regressions: list[tuple[str, int, int]] = []
    for tid, n in sorted(actual.items()):
        budget = baseline_counts.get(tid, 0)
        if n > budget:
            regressions.append((tid, budget, n))

    sys.stdout.write("Bandit summary:\n")
    for tid in sorted(set(actual) | set(baseline_counts)):
        b = baseline_counts.get(tid, 0)
        a = actual.get(tid, 0)
        marker = "  "
        if a > b:
            marker = "!!"
        elif a < b:
            marker = "↓ "
        sys.stdout.write(f"  {marker} {tid}: baseline={b}, actual={a}\n")

    if not regressions:
        sys.stdout.write("\nNo new high/medium issues. OK.\n")
        return 0

    sys.stderr.write(
        f"\nNEW issues above baseline ({len(regressions)} test-id(s)):\n"
    )
    for tid, b, a in regressions:
        sys.stderr.write(f"  {tid}: baseline={b}, actual={a} (+{a - b})\n")
    sys.stderr.write(
        "\nEither fix the introduced issues, or — if intentional — bump the\n"
        "baseline in quality/bandit-baseline.json with a justification.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
