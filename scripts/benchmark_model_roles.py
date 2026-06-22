#!/usr/bin/env python3
"""
scripts/benchmark_model_roles.py

CLI for the real-limited model-role benchmark.

Usage:
    # Mock mode (no LLM calls, deterministic):
    python scripts/benchmark_model_roles.py --mock --json

    # Real mode — forge-builder against specific providers:
    python scripts/benchmark_model_roles.py --role forge-builder --real \\
        --providers openrouter,ollama --json \\
        --output workspace/model_role_benchmark_forge_builder.json

    # Real mode — multi-role benchmark:
    python scripts/benchmark_model_roles.py --real \\
        --roles forge-builder,scout-research,shadow-advisor \\
        --providers openrouter,ollama --json \\
        --output workspace/model_role_benchmark_multi_role.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on path when called from any directory
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:  # noqa: BLE001
        pass


_BEA_ROOT = _ROOT
for _candidate in [
    _ROOT,
    Path("C:/Users/maxen/Documents/Béa"),
]:
    _env_path = _candidate / ".env"
    if _env_path.exists():
        _load_env(_env_path)
        _BEA_ROOT = _candidate
        break


from core.evaluation.model_role_benchmark import (  # noqa: E402
    _OLLAMA_BASE,
    _OLLAMA_DEFAULT_MODEL,
    _OPENROUTER_BASE,
    _OPENROUTER_DEFAULT_MODEL,
    run_benchmark,
)

_SUPPORTED_ROLES = ["forge-builder", "scout-research", "shadow-advisor"]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Real-limited model-role benchmark for Béa.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    role_group = p.add_mutually_exclusive_group()
    role_group.add_argument(
        "--role",
        default=None,
        help="Single role to benchmark (default: forge-builder)",
    )
    role_group.add_argument(
        "--roles",
        default=None,
        help=f"Comma-separated roles (supported: {', '.join(_SUPPORTED_ROLES)})",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic mock responses (no real LLM calls)",
    )
    mode.add_argument(
        "--real",
        action="store_true",
        help="Use real LLM providers (requires API keys)",
    )
    p.add_argument(
        "--providers",
        default="openrouter,ollama",
        help="Comma-separated provider list (default: openrouter,ollama)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    p.add_argument(
        "--output",
        metavar="PATH",
        help="Write JSON results to this file path",
    )
    p.add_argument(
        "--openrouter-model",
        default=_OPENROUTER_DEFAULT_MODEL,
        help=f"OpenRouter model slug (default: {_OPENROUTER_DEFAULT_MODEL})",
    )
    p.add_argument(
        "--ollama-model",
        default=None,
        help="Ollama model name (default: from settings or gemma4:12b)",
    )
    return p


def _resolve_ollama_model(cli_model: str | None) -> str:
    if cli_model:
        return cli_model
    try:
        from config.settings import get_settings
        s = get_settings()
        return s.ollama_model_main or _OLLAMA_DEFAULT_MODEL
    except Exception:  # noqa: BLE001
        return _OLLAMA_DEFAULT_MODEL


def _resolve_ollama_base() -> str:
    try:
        from config.settings import get_settings
        s = get_settings()
        host = s.ollama_host or "127.0.0.1:11434"
        if not host.startswith("http"):
            host = f"http://{host}"
        host = host.replace("http://0.0.0.0:", "http://127.0.0.1:")
        return host
    except Exception:  # noqa: BLE001
        return _OLLAMA_BASE


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.mock and not args.real:
        args.mock = True

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    ollama_model = _resolve_ollama_model(args.ollama_model)
    ollama_base = _resolve_ollama_base()

    # Resolve role(s)
    if args.roles:
        role_list = [r.strip() for r in args.roles.split(",") if r.strip()]
        report = run_benchmark(
            roles=role_list,
            providers=providers,
            mock=args.mock,
            openrouter_api_key=api_key,
            openrouter_base_url=_OPENROUTER_BASE,
            openrouter_model=args.openrouter_model,
            ollama_base_url=ollama_base,
            ollama_model=ollama_model,
        )
    else:
        single_role = args.role or "forge-builder"
        report = run_benchmark(
            role=single_role,
            providers=providers,
            mock=args.mock,
            openrouter_api_key=api_key,
            openrouter_base_url=_OPENROUTER_BASE,
            openrouter_model=args.openrouter_model,
            ollama_base_url=ollama_base,
            ollama_model=ollama_model,
        )

    # Sanity check: ensure no API key leaked into report
    report_str = json.dumps(report)
    if api_key and api_key in report_str:
        print("[SECURITY] API key detected in report — aborting.", file=sys.stderr)
        sys.exit(2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if not args.json_output:
            print(f"Report written to {out_path}")

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    # Exit non-zero only if every non-skipped result failed
    non_skipped = [r for r in report["results"] if not r.get("skipped")]
    if non_skipped and not any(r["passed"] for r in non_skipped):
        sys.exit(1)


def _print_human(report: dict) -> None:
    mode = report.get("mode", "?")
    if "roles" in report:
        print(f"Benchmark [{mode}] roles={','.join(report['roles'])}")
    else:
        print(f"Benchmark [{mode}] role={report.get('role', '?')}")
    print("-" * 60)
    for r in report.get("results", []):
        if r.get("skipped"):
            print(f"  {r['role']:18s}  {r['provider_used']:12s}  SKIPPED  ({r.get('skip_reason', '')})")
        else:
            status = "PASS" if r["passed"] else "FAIL"
            print(
                f"  {r['role']:18s}  {r['provider_used']:12s}  {status}  "
                f"score={r['score']:.2f}  dur={r['duration_s']:.1f}s"
            )
            if r.get("error_category"):
                print(f"    error_category={r['error_category']}")
    summary = report.get("summary")
    if summary:
        print("\nBest by role:")
        for role, best in summary.get("best_by_role", {}).items():
            print(
                f"  {role:18s}  {best['provider_used']:12s}  "
                f"score={best['score']:.2f}  passed={best['passed']}"
            )


if __name__ == "__main__":
    main()
