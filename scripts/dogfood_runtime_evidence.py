#!/usr/bin/env python3
"""
scripts/dogfood_runtime_evidence.py

Controlled dogfood runtime evidence pack.

Modes:
    fixture - deterministic local evidence, no live LLM calls
    real    - use a real benchmark artifact if present, or run the benchmark
              script when the environment is ready

The pack contains 10 missions, per-mission JSON reports compatible with the
mission ingestion pipeline, and a top-level summary report.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.evaluation.dogfood_report import compute_dogfood_summary, validate_mission  # noqa: E402
from core.evaluation.routing_advisor import build_advisory_report  # noqa: E402

DEFAULT_BENCHMARK = ROOT / "workspace" / "model_role_benchmark_multi_role.json"
DEFAULT_OUTPUT = ROOT / "workspace" / "dogfood_runtime_evidence.json"
DEFAULT_REPORT_DIR = ROOT / "workspace" / "dogfood_runtime_reports"


_BENCHMARK_FIXTURE: list[dict[str, Any]] = [
    {
        "role": "forge-builder",
        "provider_used": "openrouter",
        "model_used": "openai/gpt-oss-120b:free",
        "success": True,
        "passed": True,
        "score": 1.0,
        "duration_s": 21.62,
        "fallback_used": False,
        "error_category": None,
        "skipped": False,
        "skip_reason": None,
        "artifact_ok": True,
        "syntax_valid": True,
        "test_proof": True,
    },
    {
        "role": "forge-builder",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "success": False,
        "passed": False,
        "score": 0.0,
        "duration_s": 19.86,
        "fallback_used": False,
        "error_category": "artifact_invalid",
        "skipped": False,
        "skip_reason": None,
        "artifact_ok": False,
        "syntax_valid": False,
        "test_proof": False,
    },
    {
        "role": "scout-research",
        "provider_used": "openrouter",
        "model_used": "openai/gpt-oss-120b:free",
        "success": True,
        "passed": True,
        "score": 1.0,
        "duration_s": 18.19,
        "fallback_used": False,
        "error_category": None,
        "skipped": False,
        "skip_reason": None,
        "structured_output": True,
        "timeout": False,
        "local_docs_used": True,
    },
    {
        "role": "scout-research",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "success": True,
        "passed": True,
        "score": 1.0,
        "duration_s": 24.84,
        "fallback_used": False,
        "error_category": None,
        "skipped": False,
        "skip_reason": None,
        "structured_output": True,
        "timeout": False,
        "local_docs_used": True,
    },
    {
        "role": "shadow-advisor",
        "provider_used": "openrouter",
        "model_used": "openai/gpt-oss-120b:free",
        "success": True,
        "passed": True,
        "score": 1.0,
        "duration_s": 4.16,
        "fallback_used": False,
        "error_category": None,
        "skipped": False,
        "skip_reason": None,
        "json_valid": True,
        "schema_valid": True,
        "retry_count": 1,
    },
    {
        "role": "shadow-advisor",
        "provider_used": "ollama",
        "model_used": "gemma4:12b",
        "success": True,
        "passed": False,
        "score": 0.3333,
        "duration_s": 16.03,
        "fallback_used": False,
        "error_category": "json_invalid",
        "skipped": False,
        "skip_reason": None,
        "json_valid": False,
        "schema_valid": False,
        "retry_count": 1,
    },
]


_MISSION_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "mission_id": "identity",
        "role": "shadow-advisor",
        "goal": "Béa se présente, explique son rôle, cite ses capacités.",
        "kind": "analysis",
        "benchmark_role": "shadow-advisor",
        "benchmark_provider": "openrouter",
        "task_type": "analysis",
        "title": "Identity intro",
        "lessons_learned": "Keep the identity answer concise and capability-focused.",
        "model_class": "SMALL_FAST",
    },
    {
        "mission_id": "security-fastapi",
        "role": "shadow-advisor",
        "goal": "Analyse sécurité FastAPI : TLS, JWT/OAuth2, rate-limit, monitoring.",
        "kind": "analysis",
        "benchmark_role": "shadow-advisor",
        "benchmark_provider": "openrouter",
        "task_type": "security",
        "title": "Security review",
        "lessons_learned": "Security analysis should stay structured and actionable.",
        "model_class": "STRONG_CODE_REVIEW",
    },
    {
        "mission_id": "forge-builder-sha256",
        "role": "forge-builder",
        "goal": "Crée sha256_file(path: str) -> str avec test.",
        "kind": "code",
        "benchmark_role": "forge-builder",
        "benchmark_provider": "openrouter",
        "task_type": "coding",
        "title": "SHA256 helper",
        "files_changed": ["src/sha256_file.py", "tests/test_sha256_file.py"],
        "tests_run": ["python -m pytest tests/test_sha256_file.py -q"],
        "artifacts": ["file:src/sha256_file.py", "file:tests/test_sha256_file.py"],
        "lessons_learned": "Source extraction, syntax validation, and test proof are all required.",
        "model_class": "MEDIUM_TOOL_USE",
    },
    {
        "mission_id": "forge-builder-mini-refactor",
        "role": "forge-builder",
        "goal": "Crée une petite fonction utilitaire pure avec test.",
        "kind": "code",
        "benchmark_role": "forge-builder",
        "benchmark_provider": "ollama",
        "task_type": "coding",
        "title": "Mini refactor",
        "files_changed": [],
        "tests_run": [],
        "artifacts": [],
        "failure_reason": "artifact_missing",
        "lessons_learned": "A code mission needs a verifiable artifact, not just prose.",
        "model_class": "MEDIUM_TOOL_USE",
    },
    {
        "mission_id": "scout-alpha-risks",
        "role": "scout-research",
        "goal": "Analyse docs/ALPHA_READINESS.md et liste les risques alpha restants.",
        "kind": "analysis",
        "benchmark_role": "scout-research",
        "benchmark_provider": "openrouter",
        "task_type": "analysis",
        "title": "Alpha risk scan",
        "lessons_learned": "Document the remaining risks, not the historical route taken.",
        "model_class": "SMALL_FAST",
    },
    {
        "mission_id": "scout-routing-policy",
        "role": "scout-research",
        "goal": "Analyse docs/MODEL_ROUTING.md et résume la policy advisory.",
        "kind": "analysis",
        "benchmark_role": "scout-research",
        "benchmark_provider": "ollama",
        "task_type": "analysis",
        "title": "Routing policy review",
        "lessons_learned": "Advisory text must stay informational and non-prescriptive.",
        "model_class": "SMALL_FAST",
    },
    {
        "mission_id": "shadow-json-alpha",
        "role": "shadow-advisor",
        "goal": "Retourne uniquement un JSON valide avec risk_level, blockers, degraded_risks, recommended_next_action, confidence.",
        "kind": "json",
        "benchmark_role": "shadow-advisor",
        "benchmark_provider": "openrouter",
        "task_type": "json",
        "title": "Alpha JSON",
        "lessons_learned": "JSON-only output is part of the contract.",
        "model_class": "STRONG_CODE_REVIEW",
    },
    {
        "mission_id": "shadow-json-release",
        "role": "shadow-advisor",
        "goal": "Retourne uniquement un JSON valide de release readiness.",
        "kind": "json",
        "benchmark_role": "shadow-advisor",
        "benchmark_provider": "ollama",
        "task_type": "json",
        "title": "Release JSON",
        "failure_reason": "markdown_wrapper",
        "lessons_learned": "Markdown wrappers invalidate strict JSON evidence.",
        "model_class": "STRONG_CODE_REVIEW",
    },
    {
        "mission_id": "planning-next-prs",
        "role": "scout-research",
        "goal": "Propose les 3 prochaines PRs prioritaires.",
        "kind": "analysis",
        "benchmark_role": "scout-research",
        "benchmark_provider": "openrouter",
        "task_type": "planning",
        "title": "Next PRs",
        "lessons_learned": "Prioritization should remain short and concrete.",
        "model_class": "SMALL_FAST",
    },
    {
        "mission_id": "provider-fallback-test",
        "role": "forge-builder",
        "goal": "Vérifie que provider/model/fallback sont correctement enregistrés dans le rapport.",
        "kind": "verification",
        "benchmark_role": "forge-builder",
        "benchmark_provider": "openrouter",
        "task_type": "verification",
        "title": "Provider trace check",
        "files_changed": [],
        "tests_run": [],
        "artifacts": ["report:provider/model/fallback fields"],
        "lessons_learned": "Provider metadata must survive the runtime write path.",
        "model_class": "MEDIUM_TOOL_USE",
    },
]


def _security_guard(report: dict[str, Any]) -> None:
    payload = json.dumps(report, ensure_ascii=False)
    if "sk-or-v1" in payload or "Bearer " in payload:
        raise RuntimeError("Credential pattern detected in dogfood runtime evidence")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _benchmark_fixture() -> dict[str, Any]:
    return {
        "mode": "fixture",
        "roles": ["forge-builder", "scout-research", "shadow-advisor"],
        "providers": ["openrouter", "ollama"],
        "results": _BENCHMARK_FIXTURE,
    }


def _run_live_benchmark(output_dir: Path) -> tuple[dict[str, Any] | None, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = output_dir / "model_role_benchmark_multi_role.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "benchmark_model_roles.py"),
        "--real",
        "--roles",
        "forge-builder,scout-research,shadow-advisor",
        "--providers",
        "openrouter,ollama",
        "--json",
        "--output",
        str(benchmark_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if benchmark_path.exists():
        data = _load_json(benchmark_path)
        if data:
            return data, str(benchmark_path)
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout), "live benchmark stdout"
        except json.JSONDecodeError:
            pass
    return None, f"benchmark failed: rc={proc.returncode} stderr={proc.stderr.strip()[:200]}"


def _resolve_benchmark(mode: str, benchmark_path: Path | None, work_dir: Path) -> tuple[dict[str, Any], str]:
    if mode == "fixture":
        if benchmark_path:
            data = _load_json(benchmark_path)
            if data and data.get("results"):
                return data, str(benchmark_path)
        return _benchmark_fixture(), "built-in fixture"

    if benchmark_path:
        data = _load_json(benchmark_path)
        if data and data.get("mode") == "real" and data.get("results"):
            return data, str(benchmark_path)

    live_data, source = _run_live_benchmark(work_dir / "benchmark")
    if live_data and live_data.get("results"):
        return live_data, source

    return {
        "mode": "real",
        "results": [
            {
                "role": spec["role"],
                "provider_used": None,
                "model_used": None,
                "success": False,
                "passed": False,
                "score": 0.0,
                "duration_s": 0.0,
                "fallback_used": False,
                "error_category": "provider_unavailable",
                "skipped": True,
                "skip_reason": "provider_unavailable",
            }
            for spec in _MISSION_BLUEPRINTS
        ],
    }, "provider_unavailable"


def _advice_map(results: list[dict[str, Any]], source_label: str) -> dict[str, dict[str, Any]]:
    advisory = build_advisory_report(results, source_file=source_label)
    return advisory.get("recommendations", {})


def _index_results(results: list[dict[str, Any]]) -> dict[tuple[str, str | None], dict[str, Any]]:
    idx: dict[tuple[str, str | None], dict[str, Any]] = {}
    for result in results:
        idx[(result.get("role", ""), result.get("provider_used"))] = result
    return idx


def _pick_result(
    spec: dict[str, Any],
    benchmark_results: list[dict[str, Any]],
    benchmark_index: dict[tuple[str, str | None], dict[str, Any]],
) -> dict[str, Any]:
    exact = benchmark_index.get((spec["benchmark_role"], spec["benchmark_provider"]))
    if exact:
        return dict(exact)

    for result in benchmark_results:
        if result.get("role") == spec["benchmark_role"] and not result.get("skipped"):
            return dict(result)

    for result in benchmark_results:
        if result.get("role") == spec["benchmark_role"]:
            return dict(result)

    return {
        "role": spec["benchmark_role"],
        "provider_used": None,
        "model_used": None,
        "success": False,
        "passed": False,
        "score": 0.0,
        "duration_s": 0.0,
        "fallback_used": False,
        "error_category": "provider_unavailable",
        "skipped": True,
        "skip_reason": "provider_unavailable",
    }


def _mission_status_from_result(result: dict[str, Any]) -> tuple[str, bool, str]:
    if result.get("skipped"):
        return "SKIPPED", False, result.get("skip_reason") or "provider_unavailable"
    if result.get("passed"):
        return "SUCCESS", True, ""
    return "FAILURE", False, result.get("error_category") or "quality_below_threshold"


def _tools_for_spec(spec: dict[str, Any]) -> list[str]:
    task_type = spec.get("task_type")
    if task_type == "coding":
        return ["python", "pytest", "py_compile"]
    if task_type == "json":
        return ["json-schema"]
    if task_type == "verification":
        return ["report-check"]
    if task_type == "security":
        return ["docs-review"]
    return ["docs-review"]


def _plan_steps_for_spec(spec: dict[str, Any]) -> list[str]:
    base = [
        f"Load mission blueprint for {spec['mission_id']}",
        f"Execute {spec.get('task_type', 'analysis')} pass",
        "Write mission report",
    ]
    if spec.get("task_type") == "coding":
        base.insert(2, "Run syntax and test proof")
    return base


def _mission_report_dir(output_path: Path) -> Path:
    return output_path.parent / f"{output_path.stem}_reports"


def _build_mission_report(
    spec: dict[str, Any],
    result: dict[str, Any],
    *,
    mode: str,
    report_dir: Path,
    advised_provider: str | None,
) -> dict[str, Any]:
    status, success, failure_reason = _mission_status_from_result(result)
    provider_used = result.get("provider_used")
    model_used = result.get("model_used")
    fallback_used = bool(result.get("fallback_used"))
    provider_status = (
        "provider_unavailable"
        if result.get("skipped")
        else ("fallback" if fallback_used else ("fixture" if mode == "fixture" else "ready"))
    )
    matched_advice = bool(advised_provider and provider_used == advised_provider and not result.get("skipped"))
    score = float(result.get("score", 0.0) or 0.0)
    duration_s = float(result.get("duration_s", 0.0) or 0.0)

    report = {
        "mission_id": spec["mission_id"],
        "role": spec["role"],
        "title": spec["title"],
        "status": status,
        "task_type": spec["task_type"],
        "mission_type": spec["task_type"],
        "files_changed": list(spec.get("files_changed", [])),
        "tests_run": list(spec.get("tests_run", [])),
        "agents_used": [spec["role"]],
        "tools_used": _tools_for_spec(spec),
        "plan_steps": _plan_steps_for_spec(spec),
        "complexity": spec.get("model_class", "unknown"),
        "success": success,
        "failure_reason": failure_reason,
        "model_used": model_used or "",
        "model_class": spec.get("model_class", ""),
        "duration_ms": int(duration_s * 1000),
        "duration_s": duration_s,
        "cost_estimate": None,
        "lessons_learned": spec.get("lessons_learned", ""),
        "risks_detected": list(spec.get("risks_detected", [])),
        "created_at": datetime.now(timezone.utc).timestamp(),
        "provider_used": provider_used,
        "fallback_used": fallback_used,
        "provider_status": provider_status,
        "runtime_enforced": False,
        "matched_advice": matched_advice,
        "skipped": bool(result.get("skipped")),
        "skip_reason": result.get("skip_reason"),
        "passed": bool(result.get("passed")),
        "score": score,
        "mode": mode,
        "advised_provider": advised_provider,
        "goal": spec["goal"],
        "report_path": "",
        "artifacts": list(spec.get("artifacts", [])),
        "error_category": result.get("error_category"),
    }
    report_path = report_dir / f"{spec['mission_id']}.json"
    report["report_path"] = str(report_path)
    return report


def _build_pack(
    *,
    mode: str,
    benchmark: dict[str, Any],
    source_label: str,
    max_missions: int,
    output_path: Path,
) -> dict[str, Any]:
    report_dir = _mission_report_dir(output_path)
    report_dir.mkdir(parents=True, exist_ok=True)
    benchmark_results = list(benchmark.get("results", []))
    benchmark_index = _index_results(benchmark_results)
    advice = _advice_map(benchmark_results, source_label)

    missions: list[dict[str, Any]] = []
    for spec in _MISSION_BLUEPRINTS[:max_missions]:
        result = _pick_result(spec, benchmark_results, benchmark_index)
        advised_provider = (advice.get(spec["role"], {}) or {}).get("preferred_provider")
        mission_report = _build_mission_report(
            spec,
            result,
            mode=mode,
            report_dir=report_dir,
            advised_provider=advised_provider,
        )
        # Write per-mission report for ingestion compatibility.
        Path(mission_report["report_path"]).write_text(
            json.dumps(mission_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        missions.append(mission_report)

    validation_errors: list[str] = []
    for mission in missions:
        errs = validate_mission(mission)
        if errs:
            validation_errors.extend([f"{mission['mission_id']}: {err}" for err in errs])

    summary = compute_dogfood_summary(missions)
    provider_breakdown = summary.get("provider_breakdown", {})
    role_breakdown = summary.get("role_breakdown", {})
    summary["matched_advice_count"] = summary.get("matched_advice_count", summary.get("matched_advice", 0))
    summary["runtime_enforced"] = False

    report = {
        "mode": mode,
        "runtime_enforced": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_label,
        "caveat": (
            "Fixture mode uses deterministic evidence." if mode == "fixture"
            else "Real mode uses benchmark artifacts when available; provider_unavailable is surfaced explicitly."
        ),
        "missions": missions,
        "summary": summary,
        "provider_breakdown": provider_breakdown,
        "role_breakdown": role_breakdown,
    }
    if validation_errors:
        report["validation_errors"] = validation_errors
    _security_guard(report)
    return report


def build_dogfood_runtime_evidence(
    *,
    mode: str = "fixture",
    benchmark_path: str | Path | None = None,
    output_path: str | Path | None = None,
    max_missions: int = 10,
) -> dict[str, Any]:
    output = Path(output_path) if output_path else DEFAULT_OUTPUT
    benchmark, source_label = _resolve_benchmark(
        mode,
        Path(benchmark_path) if benchmark_path else None,
        output.parent,
    )
    return _build_pack(
        mode=mode,
        benchmark=benchmark,
        source_label=source_label,
        max_missions=max_missions,
        output_path=output,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a controlled dogfood runtime evidence pack.")
    parser.add_argument("--mode", choices=["fixture", "real"], default="fixture")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    parser.add_argument("--max-missions", type=int, default=10)
    return parser


def _print_human(report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    print(f"[Dogfood Runtime Evidence] mode={report.get('mode')} runtime_enforced={report.get('runtime_enforced')}")
    print(f"Source: {report.get('source', '?')}")
    print(
        f"Total={summary.get('total', 0)} passed={summary.get('passed', 0)} "
        f"failed={summary.get('failed', 0)} skipped={summary.get('skipped', 0)}"
    )
    print(
        f"matched_advice={summary.get('matched_advice_count', 0)}/{summary.get('total', 0)} "
        f"rate={summary.get('advice_match_rate', 0.0):.0%}"
    )
    print("-" * 70)
    for mission in report.get("missions", []):
        status = "PASS" if mission.get("passed") else ("SKIP" if mission.get("skipped") else "FAIL")
        print(
            f"  {mission['mission_id']:24s} {mission['role']:18s} "
            f"provider={mission.get('provider_used') or 'none'} "
            f"score={mission.get('score', 0.0):.2f} [{status}] "
            f"matched={mission.get('matched_advice')}"
        )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    report = build_dogfood_runtime_evidence(
        mode=args.mode,
        benchmark_path=args.benchmark,
        output_path=args.output,
        max_missions=args.max_missions,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
