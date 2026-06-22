#!/usr/bin/env python3
"""Local mission observability report from learning_runs.json.

Usage:
    python scripts/mission_status_report.py
    python scripts/mission_status_report.py --json

Prompts and LLM responses are never included. Secrets are redacted.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
LEARNING_RUNS = ROOT / "workspace" / "learning_runs.json"


def load_runs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
    except Exception:
        return []
    return []


def compute_report(runs: list[dict]) -> dict:
    total = len(runs)
    if total == 0:
        return {"total": 0, "message": "No learning runs found in workspace/learning_runs.json"}

    success = sum(
        1 for r in runs
        if r.get("success") or r.get("status") in ("success", "SUCCESS")
    )
    failed = total - success

    durations = [
        r["duration_s"] for r in runs
        if isinstance(r.get("duration_s"), (int, float))
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    error_cats = Counter(
        r.get("error_category") for r in runs
        if r.get("error_category") and r.get("error_category") not in (None, "none", "null")
    )
    providers = Counter(r.get("provider_used") for r in runs if r.get("provider_used"))
    models = Counter(r.get("model_used") for r in runs if r.get("model_used"))
    artifact_invalid = sum(1 for r in runs if r.get("error_category") == "artifact_invalid")
    provider_unavailable = sum(
        1 for r in runs if r.get("error_category") == "provider_unavailable"
    )
    rate_limited = sum(
        1 for r in runs
        if r.get("rate_limited") or r.get("error_category") == "rate_limited"
    )

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "artifact_invalid": artifact_invalid,
        "provider_unavailable": provider_unavailable,
        "rate_limited": rate_limited,
        "avg_duration_s": avg_duration,
        "top_error_categories": dict(error_cats.most_common(5)),
        "providers_used": dict(providers.most_common()),
        "models_used": dict(models.most_common(5)),
        "privacy_note": "Prompts and responses are never included. Secrets are redacted.",
    }


def main() -> int:
    runs = load_runs(LEARNING_RUNS)
    report = compute_report(runs)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return 0
    total = report.get("total", 0)
    print(f"Missions: {total} total / {report.get('success', 0)} success / {report.get('failed', 0)} failed")
    if report.get("avg_duration_s"):
        print(f"Avg duration: {report['avg_duration_s']}s")
    if report.get("artifact_invalid"):
        print(f"Artifact invalid: {report['artifact_invalid']}")
    if report.get("provider_unavailable"):
        print(f"Provider unavailable: {report['provider_unavailable']}")
    if report.get("rate_limited"):
        print(f"Rate limited: {report['rate_limited']}")
    if report.get("top_error_categories"):
        print(f"Top errors: {report['top_error_categories']}")
    if report.get("providers_used"):
        print(f"Providers: {report['providers_used']}")
    if report.get("models_used"):
        print(f"Models: {report['models_used']}")
    if total == 0:
        print(report.get("message", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
