"""Diagnostic script — LLM provider health check.

Prints the availability status of all configured LLM providers without
revealing any secret values.

Usage:
    python scripts/provider_healthcheck.py
    python scripts/provider_healthcheck.py --json
"""
# ruff: noqa: T201
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(args: argparse.Namespace) -> int:
    try:
        from core.providers.runtime_health import check_provider_health_sync
    except ImportError as exc:
        print(f"[ERROR] cannot import runtime_health: {exc}", file=sys.stderr)
        return 1

    try:
        health = check_provider_health_sync()
    except Exception as exc:
        print(f"[ERROR] health check failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(health.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(health)

    return 0 if health.status == "READY" else 1


def _print_human(health) -> None:
    status_icon = {"READY": "✓", "DEGRADED": "~", "UNAVAILABLE": "✗"}.get(
        health.status, "?"
    )
    print()
    print("=" * 60)
    print(f"  Béa — LLM Provider Health Check  [{health.status}] {status_icon}")
    print("=" * 60)
    print()

    # OpenRouter
    or_key = "present" if health.openrouter_key_present else "ABSENT"
    or_usable = (
        "yes" if health.openrouter_usable
        else "no" if health.openrouter_usable is False
        else "unknown"
    )
    print(f"  OpenRouter key present : {or_key}")
    print(f"  OpenRouter usable      : {or_usable}")
    print()

    # Ollama
    ollama_ok = "yes" if health.ollama_reachable else "no"
    print(f"  Ollama reachable       : {ollama_ok}")
    if health.ollama_host_used:
        print(f"  Ollama host used       : {health.ollama_host_used}")
    if health.ollama_models:
        models_str = ", ".join(health.ollama_models[:8])
        if len(health.ollama_models) > 8:
            models_str += f" (+{len(health.ollama_models) - 8} more)"
        print(f"  Ollama models          : {models_str}")
    else:
        print("  Ollama models          : none / unknown")
    print()

    # Summary
    print(f"  Default provider       : {health.default_provider}")
    print(f"  Fallback provider      : {health.fallback_provider}")
    print(f"  Final status           : {health.status}")
    print()

    if health.hints:
        print("  Hints:")
        for hint in health.hints:
            for line in _wrap(hint, 56):
                print(f"    {line}")
        print()

    print("=" * 60)
    print()


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap helper."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines or [""]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check LLM provider availability for Béa."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of human-readable text.",
    )
    args = parser.parse_args()
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
