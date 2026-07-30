#!/usr/bin/env python3
"""
scripts/benchmark_model_roles.py — Benchmark agent roles against available models.

Usage:
    python scripts/benchmark_model_roles.py --list
    python scripts/benchmark_model_roles.py --mock --json
    python scripts/benchmark_model_roles.py --role forge-builder --provider openrouter --json
    python scripts/benchmark_model_roles.py --role shadow-advisor --provider ollama --json
    python scripts/benchmark_model_roles.py --mock --output workspace/model_role_benchmark.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make repo imports work when invoked as script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.evaluation.model_role_benchmark import (
    AgentRole,
    BenchmarkResult,
    get_fixtures,
    run_fixture,
)


def _stdout(text: str) -> None:
    sys.stdout.write(text + "\n")


def _list_fixtures() -> None:
    _stdout("Available benchmark fixtures")
    _stdout("-" * 40)
    for fixture in get_fixtures():
        _stdout(f"{fixture.role.value:20} {fixture.name:20} {fixture.mission_type}")


def _redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove anything that looks like an API key from a JSON-serializable dict."""
    sensitive_keys = {"api_key", "apikey", "key", "token", "secret", "password"}
    return _redact_value(payload, sensitive_keys)


def _redact_value(value: Any, sensitive_keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            k: "***REDACTED***" if k.lower() in sensitive_keys else _redact_value(v, sensitive_keys)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(v, sensitive_keys) for v in value]
    if isinstance(value, str):
        # Heuristic: long hex/base64 strings that could be keys
        if len(value) >= 32 and value.strip():
            return "***REDACTED***"
    return value


def _run_benchmark(
    role_filter: AgentRole | None,
    provider: str,
    model: str,
    mock: bool,
) -> list[BenchmarkResult]:
    fixtures = get_fixtures(role_filter)
    results: list[BenchmarkResult] = []
    for fixture in fixtures:
        result = run_fixture(fixture, provider=provider, model=model, mock=mock)
        results.append(result)
    return results


def _print_report(results: list[BenchmarkResult]) -> None:
    _stdout("Model role benchmark")
    _stdout("=" * 50)
    for result in results:
        status = "PASS" if result.success else "FAIL"
        _stdout(
            f"[{status}] {result.role.value:16} {result.fixture_name:16} "
            f"score={result.score:.2f} duration={result.duration_s:.1f}s "
            f"provider={result.provider_used} model={result.model_used}"
        )
        if result.error_category.value != "none":
            _stdout(f"       error={result.error_category.value}")
    _stdout("")
    avg_score = sum(r.score for r in results) / max(len(results), 1)
    _stdout(f"Average score: {avg_score:.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark agent roles against LLM providers/models")
    parser.add_argument("--list", action="store_true", help="List available fixtures")
    parser.add_argument("--role", type=str, default="", help="Role to benchmark (forge-builder|scout-research|shadow-advisor)")
    parser.add_argument("--provider", type=str, default="", help="Provider override, e.g. openrouter or ollama")
    parser.add_argument("--model", type=str, default="", help="Model name override")
    parser.add_argument("--mock", action="store_true", help="Use deterministic mock output (no LLM calls)")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--output", type=str, default="", help="Write JSON output to file")
    args = parser.parse_args(argv)

    if args.list:
        _list_fixtures()
        return 0

    role_filter: AgentRole | None = None
    if args.role:
        try:
            role_filter = AgentRole(args.role)
        except ValueError:
            sys.stderr.write(f"ERROR: unknown role '{args.role}'. Use --list to see roles.\n")
            return 2

    results = _run_benchmark(
        role_filter=role_filter,
        provider=args.provider,
        model=args.model,
        mock=args.mock,
    )

    report = {
        "mock": args.mock,
        "results": [r.to_dict() for r in results],
        "average_score": round(sum(r.score for r in results) / max(len(results), 1), 3),
    }
    report = _redact_secrets(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        _stdout(f"Report written to {out_path}")

    if args.json:
        _stdout(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
