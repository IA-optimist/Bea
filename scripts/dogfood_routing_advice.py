#!/usr/bin/env python3
"""
scripts/dogfood_routing_advice.py

Dogfood routing-advice evidence pack (fixture mode).

Loads the current advisory (from a benchmark file or built-in fixture),
runs 5 predefined missions in fixture mode, compares provider_used vs
advised_provider, and writes a structured evidence report.

Usage:
    python scripts/dogfood_routing_advice.py --json
    python scripts/dogfood_routing_advice.py --json --output workspace/dogfood_routing_advice_report.json

Mode is always "fixture" — results are pre-defined, not from live LLM calls.
runtime_enforced is always false.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.evaluation.dogfood_report import compute_dogfood_summary, validate_mission  # noqa: E402
from core.evaluation.routing_advisor import build_advisory_report  # noqa: E402

_DEFAULT_BENCHMARK_FILE = _ROOT / "workspace" / "model_role_benchmark_multi_role.json"

# ── Built-in benchmark fixture (used when workspace file is absent) ────────────

_BENCHMARK_FIXTURE: list[dict] = [
    {
        "role": "forge-builder",
        "provider_used": "openrouter",
        "model_used": "gpt-oss-120b:free",
        "score": 1.0,
        "passed": True,
        "success": True,
        "skipped": False,
        "duration_s": 18.2,
        "fallback_used": False,
        "error_category": None,
    },
    {
        "role": "forge-builder",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "score": 0.0,
        "passed": False,
        "success": False,
        "skipped": False,
        "duration_s": 40.0,
        "fallback_used": False,
        "error_category": "artifact_invalid",
    },
    {
        "role": "scout-research",
        "provider_used": "openrouter",
        "model_used": "gpt-oss-120b:free",
        "score": 1.0,
        "passed": True,
        "success": True,
        "skipped": False,
        "duration_s": 22.1,
        "fallback_used": False,
        "error_category": None,
    },
    {
        "role": "scout-research",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "score": 1.0,
        "passed": True,
        "success": True,
        "skipped": False,
        "duration_s": 45.3,
        "fallback_used": False,
        "error_category": None,
    },
    {
        "role": "shadow-advisor",
        "provider_used": "openrouter",
        "model_used": "gpt-oss-120b:free",
        "score": 1.0,
        "passed": True,
        "success": True,
        "skipped": False,
        "duration_s": 8.7,
        "fallback_used": False,
        "error_category": None,
    },
    {
        "role": "shadow-advisor",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "score": 0.33,
        "passed": False,
        "success": True,
        "skipped": False,
        "duration_s": 38.0,
        "fallback_used": False,
        "error_category": "json_invalid",
    },
]

# ── Dogfood fixture missions ──────────────────────────────────────────────────

def _build_fixture_missions(advice: dict) -> list[dict]:
    """Return the 5 predefined dogfood missions with matched_advice computed."""

    def _advised(role: str) -> str | None:
        rec = advice.get(role, {})
        return rec.get("preferred_provider")

    def _advised_model(role: str) -> str | None:
        rec = advice.get(role, {})
        return rec.get("preferred_model")

    missions = [
        # A — forge-builder simple
        {
            "mission_id": "dogfood-A",
            "role": "forge-builder",
            "goal": "Créer une fonction Python sha256_file(path: str) -> str avec test unitaire",
            "advised_provider": _advised("forge-builder"),
            "provider_used": "openrouter",
            "model_used": _advised_model("forge-builder") or "gpt-oss-120b:free",
            "success": True,
            "passed": True,
            "score": 1.0,
            "duration_s": 18.2,
            "artifact_ok": True,
            "syntax_valid": True,
            "test_proof": True,
            "fallback_used": False,
            "error_category": None,
            "skipped": False,
            "runtime_enforced": False,
        },
        # B — forge-builder mini-refactor
        {
            "mission_id": "dogfood-B",
            "role": "forge-builder",
            "goal": "Créer une fonction utilitaire pure flatten_dict(d: dict) -> dict avec test",
            "advised_provider": _advised("forge-builder"),
            "provider_used": "openrouter",
            "model_used": _advised_model("forge-builder") or "gpt-oss-120b:free",
            "success": True,
            "passed": True,
            "score": 1.0,
            "duration_s": 14.5,
            "artifact_ok": True,
            "syntax_valid": True,
            "test_proof": True,
            "fallback_used": False,
            "error_category": None,
            "skipped": False,
            "runtime_enforced": False,
        },
        # C — scout-research local docs
        {
            "mission_id": "dogfood-C",
            "role": "scout-research",
            "goal": "Analyser docs/ALPHA_READINESS.md et docs/MODEL_ROUTING.md, lister les 5 risques alpha restants",
            "advised_provider": _advised("scout-research"),
            "provider_used": "openrouter",
            "model_used": _advised_model("scout-research") or "gpt-oss-120b:free",
            "success": True,
            "passed": True,
            "score": 1.0,
            "duration_s": 22.1,
            "structured_output": True,
            "timeout": False,
            "local_docs_used": True,
            "fallback_used": False,
            "error_category": None,
            "skipped": False,
            "runtime_enforced": False,
        },
        # D — shadow-advisor JSON
        {
            "mission_id": "dogfood-D",
            "role": "shadow-advisor",
            "goal": (
                "Retourner uniquement un JSON valide avec les champs "
                "risk_level, blockers, degraded_risks, recommended_next_action, confidence"
            ),
            "advised_provider": _advised("shadow-advisor"),
            "provider_used": "openrouter",
            "model_used": _advised_model("shadow-advisor") or "gpt-oss-120b:free",
            "success": True,
            "passed": True,
            "score": 1.0,
            "duration_s": 8.7,
            "json_valid": True,
            "schema_valid": True,
            "no_markdown": True,
            "retry_count": 1,
            "fallback_used": False,
            "error_category": None,
            "skipped": False,
            "runtime_enforced": False,
        },
        # E — mixed planning (partial schema, no_markdown=False)
        {
            "mission_id": "dogfood-E",
            "role": "shadow-advisor",
            "goal": (
                "À partir des derniers rapports benchmark/advisory, "
                "proposer les 3 prochaines PRs prioritaires sous forme structurée"
            ),
            "advised_provider": _advised("shadow-advisor"),
            "provider_used": "openrouter",
            "model_used": _advised_model("shadow-advisor") or "gpt-oss-120b:free",
            "success": True,
            "passed": False,
            "score": 0.67,
            "duration_s": 31.4,
            "json_valid": True,
            "schema_valid": False,
            "no_markdown": False,
            "retry_count": 1,
            "fallback_used": False,
            "error_category": "partial_schema",
            "skipped": False,
            "runtime_enforced": False,
        },
    ]

    # Compute matched_advice for each mission
    for m in missions:
        m["matched_advice"] = (
            m["provider_used"] == m["advised_provider"]
            if m["advised_provider"]
            else False
        )

    return missions


def _load_benchmark_results() -> tuple[list[dict], str]:
    """Load benchmark results; return (results, source_label)."""
    if _DEFAULT_BENCHMARK_FILE.exists():
        try:
            data = json.loads(_DEFAULT_BENCHMARK_FILE.read_text(encoding="utf-8"))
            results = data.get("results", [])
            if results:
                return results, str(_DEFAULT_BENCHMARK_FILE)
        except (json.JSONDecodeError, OSError):
            pass
    return _BENCHMARK_FIXTURE, "built-in fixture"


def build_dogfood_report() -> dict:
    """Build the complete dogfood evidence report. mode is always 'fixture'."""
    benchmark_results, source_label = _load_benchmark_results()
    advisory_report = build_advisory_report(benchmark_results, source_file=source_label)
    advice = advisory_report.get("recommendations", {})

    missions = _build_fixture_missions(advice)

    # Validate every mission
    validation_errors: list[str] = []
    for m in missions:
        errs = validate_mission(m)
        if errs:
            validation_errors.extend([f"{m['mission_id']}: {e}" for e in errs])

    summary = compute_dogfood_summary(missions)

    report = {
        "mode": "fixture",
        "runtime_enforced": False,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "advisory_source": source_label,
        "caveat": (
            "Fixture mode — missions use pre-defined results, not live LLM calls. "
            "runtime_enforced=false. Advisory is informational only."
        ),
        "missions": missions,
        "summary": summary,
    }
    if validation_errors:
        report["validation_errors"] = validation_errors

    return report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dogfood routing-advice evidence pack (fixture mode).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--json", action="store_true", dest="json_output",
                   help="Output report as JSON")
    p.add_argument("--output", metavar="PATH",
                   help="Write JSON report to this file")
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    report = build_dogfood_report()

    # Security: ensure no credential pattern leaks into JSON
    report_str = json.dumps(report)
    if "sk-or-v1" in report_str or "Bearer " in report_str:
        print("[SECURITY] Credential pattern in dogfood report — aborting.", file=sys.stderr)
        sys.exit(2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not args.json_output:
            print(f"Dogfood report written to {out_path}")

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)


def _print_human(report: dict) -> None:
    s = report.get("summary", {})
    print(f"[Dogfood Evidence Pack]  mode={report['mode']}  runtime_enforced={report['runtime_enforced']}")
    print(f"Advisory source: {report.get('advisory_source', '?')}")
    print(f"Total={s['total']}  passed={s['passed']}  failed={s['failed']}  skipped={s['skipped']}")
    print(f"matched_advice={s['matched_advice']}/{s['total']}  rate={s['advice_match_rate']:.0%}")
    print("-" * 70)
    for m in report.get("missions", []):
        status = "PASS" if m.get("passed") else ("SKIP" if m.get("skipped") else "FAIL")
        print(
            f"  {m['mission_id']}  {m['role']:18s}  "
            f"provider={m['provider_used']}  score={m['score']:.2f}  [{status}]  "
            f"matched={m.get('matched_advice')}"
        )


if __name__ == "__main__":
    main()
