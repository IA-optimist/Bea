"""Ratchet gate for quarantine/stale/xfail test markers."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_ROOT = PROJECT_ROOT / "tests"
DEFAULT_BASELINE = PROJECT_ROOT / "quality" / "test-marker-baseline.json"
MARKERS = ("quarantine", "xfail", "stale")


def scan_marker_counts(root: Path = DEFAULT_TEST_ROOT) -> dict[str, int]:
    counts: Counter[str] = Counter({marker: 0 for marker in MARKERS})
    for path in root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for marker in MARKERS:
            counts[marker] += len(re.findall(rf"\bpytest\.mark\.{re.escape(marker)}\b", text))
    return dict(counts)


def compare_marker_counts(actual: dict[str, int], baseline: dict[str, Any]) -> list[tuple[str, int, int]]:
    budget = baseline.get("markers", baseline)
    regressions: list[tuple[str, int, int]] = []
    for marker in MARKERS:
        baseline_count = int(budget.get(marker, 0))
        actual_count = int(actual.get(marker, 0))
        if actual_count > baseline_count:
            regressions.append((marker, baseline_count, actual_count))
    return regressions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_TEST_ROOT)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        sys.stderr.write(f"baseline not found: {args.baseline}\n")
        return 2

    actual = scan_marker_counts(args.root)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    regressions = compare_marker_counts(actual, baseline)
    report = {
        "markers": actual,
        "regressions": [
            {"marker": marker, "baseline": baseline_count, "actual": actual_count}
            for marker, baseline_count, actual_count in regressions
        ],
    }
    if args.report_json:
        args.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    sys.stdout.write("test marker ratchet:\n")
    for marker in MARKERS:
        sys.stdout.write(f"  {marker}: {actual.get(marker, 0)}\n")
    if not regressions:
        sys.stdout.write("test marker ratchet OK\n")
        return 0

    sys.stderr.write("test marker debt increased:\n")
    for marker, baseline_count, actual_count in regressions:
        sys.stderr.write(f"  {marker}: baseline={baseline_count}, actual={actual_count}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
