#!/usr/bin/env python3
"""CLI entry point for `bea eval`.

Usage:
    python scripts/bea_eval.py
    python scripts/bea_eval.py --evals memory-active-decision repo-map-symbols
    python scripts/bea_eval.py --list
    python scripts/bea_eval.py --json --output workspace/bea_eval_last.json
    python scripts/bea_eval.py --markdown --output workspace/bea_eval_report.md
    python scripts/bea_eval.py --json --isolated   # CI-safe: fresh temp store, no global pollution
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import singleton reset early — does not create a store, just resets it.
from core.memory.operational_memory import reset_operational_memory_store  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bea eval suite")
    parser.add_argument(
        "--evals",
        nargs="*",
        help="Specific eval names to run (default: full suite)",
    )
    parser.add_argument("--list", action="store_true", help="List available evals")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    parser.add_argument("--markdown", action="store_true", help="Print report as Markdown")
    parser.add_argument("--output", type=str, default="", help="Write report to file (extension selects format)")
    parser.add_argument("--root", type=str, default=".", help="Repository root")
    parser.add_argument(
        "--isolated",
        action="store_true",
        help=(
            "Run with a temporary isolated store. "
            "Safe for CI: does not read or write to the global operational memory DB. "
            "The temp store is deleted after the run."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    tmpdir: str | None = None
    _orig_db = os.environ.get("BEA_OPERATIONAL_MEMORY_DB")

    if args.isolated:
        tmpdir = tempfile.mkdtemp(prefix="bea_eval_isolated_")
        os.environ["BEA_OPERATIONAL_MEMORY_DB"] = os.path.join(tmpdir, "bea_eval_isolated.db")
        # Reset singleton so the next get_operational_memory_store() call creates a
        # fresh store pointing at the temp DB.
        reset_operational_memory_store()

    try:
        # Deferred imports so core.evals.bea_eval picks up the (possibly patched)
        # env var when it calls get_operational_memory_store() inside BeaEval.__init__.
        from core.evals.bea_eval import run_and_report, run_evals  # noqa: E402

        if args.list:
            from core.evals.bea_eval import BeaEval
            for name in BeaEval.EVAL_NAMES:
                print(name)
            return 0

        if args.markdown or (args.output and args.output.endswith(".md")):
            report, markdown = run_and_report(names=args.evals or None, root=args.root)
            if args.output:
                out_path = Path(args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(markdown, encoding="utf-8")
                print(f"Markdown report written to {out_path}")
            if args.markdown:
                print(markdown)
            return 0 if report.summary.get("failed", 0) == 0 else 1

        report = run_evals(names=args.evals or None, root=args.root)
        data = report.to_dict()

        if args.json or args.output:
            payload = json.dumps(data, indent=2, ensure_ascii=False)
            if args.output:
                out_path = Path(args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(payload, encoding="utf-8")
                print(f"Report written to {out_path}")
            if args.json:
                print(payload)
        else:
            print(f"bea eval run {report.run_id}")
            print(f"Overall score : {report.overall_score():.2f}")
            for r in report.results:
                status = "PASS" if r.success else "FAIL"
                model = r.model_class_selected or "-"
                print(f"  [{status}] {r.eval_name:<40} score={r.score:.2f} dur={r.duration_ms}ms model={model}")
                if r.error:
                    print(f"        error: {r.error}")

        return 0 if report.summary.get("failed", 0) == 0 else 1

    finally:
        # Always restore env and release the singleton so subsequent calls in the
        # same process use the correct store.
        if args.isolated:
            if _orig_db is None:
                os.environ.pop("BEA_OPERATIONAL_MEMORY_DB", None)
            else:
                os.environ["BEA_OPERATIONAL_MEMORY_DB"] = _orig_db
            reset_operational_memory_store()
            if tmpdir and Path(tmpdir).exists():
                shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
