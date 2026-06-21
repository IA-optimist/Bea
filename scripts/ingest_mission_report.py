#!/usr/bin/env python3
"""CLI entry point to ingest mission reports into Béa's memory.

Usage:
    python scripts/ingest_mission_report.py path/to/report.json
    python scripts/ingest_mission_report.py reports/
    python scripts/ingest_mission_report.py --json reports/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.evaluation.ingestion import ingest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest mission reports into Béa memory")
    parser.add_argument("path", help="Path to a mission report file or directory")
    parser.add_argument("--json", action="store_true", help="Output JSON summary")
    args = parser.parse_args(argv)

    result = ingest(args.path)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Ingested mission reports from {args.path}")
        print(f"  Reports read:     {result['reports_read']}")
        print(f"  Memories created: {result['memories_created']}")
        print(f"  Memories updated: {result['memories_updated']}")
        if result["warnings"]:
            print(f"  Warnings:         {len(result['warnings'])}")
            for w in result["warnings"][:5]:
                print(f"    - {w}")
        if result["errors"]:
            print(f"  Errors:           {len(result['errors'])}")
            for e in result["errors"][:5]:
                print(f"    - {e}")
        if result["details"]:
            print("  Details:")
            for d in result["details"]:
                print(f"    {d['file']}: +{d['created']} created, ~{d['updated']} updated")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
