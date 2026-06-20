"""Run the deterministic Bea benchmark and print a JSON report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.self_improvement.benchmark_harness import run_bea_benchmark  # noqa: E402
from core.coding_agent.swe_lite import run_swe_lite_v1  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Bea benchmark suite")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--swe-lite", action="store_true", help="Also run Sprint 3 SWE-lite coding-agent evaluation")
    args = parser.parse_args()

    report = run_bea_benchmark()
    data = report.to_dict()
    if args.swe_lite:
        data["swe_lite"] = run_swe_lite_v1(ROOT).to_dict()

    if args.json:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if args.swe_lite:
        sys.stdout.write(f"swe_lite: {data['swe_lite']['score']} passed={data['swe_lite']['passed']}\n")
    return 0

    sys.stdout.write(f"run_id: {data['run_id']}\n")
    sys.stdout.write(f"overall_score: {data['overall_score']}\n")
    sys.stdout.write(f"memory: {data['memory']['score']} passed={data['memory']['passed']}\n")
    sys.stdout.write(f"coding: {data['coding']['score']} passed={data['coding']['passed']}\n")
    for item in data["comparisons"]:
        sys.stdout.write(f"{item['target']}: {item['status']} by {item['delta']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
