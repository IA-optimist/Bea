#!/usr/bin/env python3
"""
scripts/model_routing_advice.py

CLI that reads a benchmark result file and produces non-prescriptive
routing recommendations per role.

Usage:
    python scripts/model_routing_advice.py \\
        --input workspace/model_role_benchmark_multi_role.json --json

Output is advisory only. The router is NOT updated automatically.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.evaluation.routing_advisor import build_advisory_report  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate non-prescriptive routing recommendations from benchmark results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input",
        required=True,
        metavar="PATH",
        help="Path to benchmark JSON file (e.g. workspace/model_role_benchmark_multi_role.json)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output recommendations as JSON",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write advisory JSON to this file (optional)",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERROR] Could not read benchmark file: {exc}", file=sys.stderr)
        sys.exit(1)

    results: list[dict] = data.get("results", [])
    if not results:
        print("[ERROR] Benchmark file contains no results.", file=sys.stderr)
        sys.exit(1)

    report = build_advisory_report(results, source_file=str(input_path))

    # Sanity check: ensure no API key pattern in output
    report_str = json.dumps(report)
    if "sk-or-v1" in report_str or "Bearer " in report_str:
        print("[SECURITY] Credential pattern detected in advisory output — aborting.", file=sys.stderr)
        sys.exit(2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not args.json_output:
            print(f"Advisory written to {out_path}")

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)


def _print_human(report: dict) -> None:
    print(f"[Advisory Mode] source={report.get('source_file', '?')}")
    print(f"Caveat: {report.get('caveat', '')}")
    print("-" * 70)
    for role, rec in report.get("recommendations", {}).items():
        provider = rec.get("preferred_provider") or "none"
        model = rec.get("preferred_model") or "n/a"
        score = rec.get("score", 0.0)
        passed = rec.get("passed_count", 0)
        failed = rec.get("failed_count", 0)
        skipped = rec.get("skipped_count", 0)
        print(
            f"  {role:18s}  preferred={provider}/{model}  "
            f"score={score:.2f}  passed={passed}  failed={failed}  skipped={skipped}"
        )
        print(f"    reason: {rec.get('reason', '')}")
        print(f"    runtime_enforced={rec.get('runtime_enforced')}  confidence={rec.get('confidence')}")


if __name__ == "__main__":
    main()
