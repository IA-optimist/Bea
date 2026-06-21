"""Ensure the official CI coverage threshold is not lowered."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CI = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_BASELINE = PROJECT_ROOT / "quality" / "coverage-baseline.json"


def extract_coverage_fail_under(ci_text: str) -> int:
    env_match = re.search(r"COVERAGE_FAIL_UNDER:-(\d+)", ci_text)
    if env_match:
        return int(env_match.group(1))
    arg_match = re.search(r"--cov-fail-under[=\s\"']+(\d+)", ci_text)
    if arg_match:
        return int(arg_match.group(1))
    raise ValueError("coverage fail-under threshold not found")


def compare_coverage_threshold(actual: int, baseline: dict[str, Any]) -> tuple[int, int] | None:
    minimum = int(baseline["min_fail_under"])
    if actual < minimum:
        return minimum, actual
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ci", type=Path, default=DEFAULT_CI)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args(argv)

    if not args.ci.exists():
        sys.stderr.write(f"CI workflow not found: {args.ci}\n")
        return 2
    if not args.baseline.exists():
        sys.stderr.write(f"coverage baseline not found: {args.baseline}\n")
        return 2

    actual = extract_coverage_fail_under(args.ci.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    regression = compare_coverage_threshold(actual, baseline)
    if regression is None:
        sys.stdout.write(f"coverage threshold OK: {actual} >= {baseline['min_fail_under']}\n")
        return 0

    minimum, lowered = regression
    sys.stderr.write(f"coverage threshold lowered: {lowered} < baseline {minimum}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
