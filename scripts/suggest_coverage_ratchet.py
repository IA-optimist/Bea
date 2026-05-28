"""Coverage ratchet helper.

Audit follow-up: CI uses ``--cov-fail-under=$COVERAGE_FAIL_UNDER`` (default
45) on ``core/api/kernel``. The audit recommends ratcheting this upward as
tests fill in the 0%-coverage modules.

This script reads a ``coverage.xml`` report (produced by ``pytest --cov``)
and prints:

  - the current measured percentage
  - a suggested next gate (current % minus 1, rounded down to int)
  - the gap to a target (default 80)
  - the modules with 0% coverage that block the next jump

Usage::

    pytest core api kernel --cov=core --cov=api --cov=kernel --cov-report=xml
    python scripts/suggest_coverage_ratchet.py coverage.xml --target 80

Designed to be run periodically (manually, or in a nightly CI job) — NOT in
the gating CI step. The gate value is bumped by hand via
``COVERAGE_FAIL_UNDER`` once the actual coverage has grown enough.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _parse_coverage(path: Path) -> tuple[float, list[tuple[str, float]]]:
    """Return (overall_percent, [(module_path, percent), ...]) from coverage.xml."""
    if not path.exists():
        raise SystemExit(f"coverage report not found: {path}")
    tree = ET.parse(path)
    root = tree.getroot()
    # Coverage.py XML schema: <coverage line-rate="0.5698" ...>
    rate_attr = root.get("line-rate")
    if rate_attr is None:
        raise SystemExit(f"unexpected coverage.xml format: missing line-rate attribute")
    overall = float(rate_attr) * 100.0

    modules: list[tuple[str, float]] = []
    for cls in root.iter("class"):
        filename = cls.get("filename") or cls.get("name") or "?"
        rate = float(cls.get("line-rate", "0")) * 100.0
        modules.append((filename, rate))
    return overall, modules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path, help="Path to coverage.xml")
    parser.add_argument(
        "--target", type=float, default=80.0,
        help="Long-term coverage target percent (default: 80)",
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Show this many lowest-coverage modules (default: 10)",
    )
    args = parser.parse_args(argv)

    overall, modules = _parse_coverage(args.coverage_xml)
    suggested = max(0, int(overall) - 1)  # one point below current = safe gate
    gap = max(0.0, args.target - overall)

    print(f"Overall coverage: {overall:.2f}%")
    print(f"Suggested next CI gate (COVERAGE_FAIL_UNDER): {suggested}")
    print(f"Gap to target ({args.target:.0f}%): {gap:.2f} percentage points")
    print()

    zero_cov = sorted([m for m, r in modules if r == 0.0])
    if zero_cov:
        print(f"Modules with 0% coverage ({len(zero_cov)}):")
        for mod in zero_cov[: args.top]:
            print(f"  {mod}")
        if len(zero_cov) > args.top:
            print(f"  ... and {len(zero_cov) - args.top} more")
        print()
        print("Hint: covering the 0% modules first gives the biggest jump per test.")

    low_cov = sorted(
        [(m, r) for m, r in modules if 0.0 < r < 50.0], key=lambda t: t[1]
    )
    if low_cov:
        print()
        print(f"Lowest non-zero coverage ({len(low_cov)} files <50%):")
        for mod, rate in low_cov[: args.top]:
            print(f"  {rate:5.1f}%  {mod}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
