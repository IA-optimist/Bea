"""Diagnostic script -- LLM provider health check.

Prints the availability status of all configured LLM providers without
revealing any secret values.

Usage:
    python scripts/provider_healthcheck.py
    python scripts/provider_healthcheck.py --json

Windows note: if the console shows garbled characters, run:
    set PYTHONIOENCODING=utf-8
before launching the script. The script also auto-detects narrow encodings
and falls back to ASCII-safe symbols automatically.
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


# -- Unicode safety -----------------------------------------------------------

def _supports_unicode() -> bool:
    """Return True when stdout can render Unicode box characters (e.g. checkmark)."""
    enc = (getattr(sys.stdout, "encoding", "") or "").replace("-", "").lower()
    return "utf" in enc


def _status_icon(status: str) -> str:
    """Return a status decoration safe for the current stdout encoding."""
    if _supports_unicode():
        return {
            "READY": "✓",      # checkmark
            "DEGRADED": "~",
            "UNAVAILABLE": "✗",  # cross
        }.get(status, "?")
    return {"READY": "OK", "DEGRADED": "~~", "UNAVAILABLE": "FAIL"}.get(status, "?")


def _safe_print(text: str = "") -> None:
    """Print to stdout; silently replace unencodable chars on narrow Windows consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        safe = text.encode(enc, errors="replace").decode(enc)
        print(safe)


# -- Core logic ---------------------------------------------------------------

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
        _print_json(health)
    else:
        _print_human(health)

    return 0 if health.status == "READY" else 1


def _print_json(health) -> None:
    """Output JSON; fall back to ASCII escapes on narrow Windows consoles."""
    payload = json.dumps(health.to_dict(), indent=2, ensure_ascii=False)
    try:
        print(payload)
    except UnicodeEncodeError:
        print(json.dumps(health.to_dict(), indent=2, ensure_ascii=True))


def _print_human(health) -> None:
    icon = _status_icon(health.status)
    _safe_print()
    _safe_print("=" * 60)
    _safe_print(f"  Bea -- LLM Provider Health Check  [{health.status}] {icon}")
    _safe_print("=" * 60)
    _safe_print()

    # OpenRouter
    or_key = "present" if health.openrouter_key_present else "ABSENT"
    or_usable = (
        "yes" if health.openrouter_usable
        else "no" if health.openrouter_usable is False
        else "unknown"
    )
    _safe_print(f"  OpenRouter key present : {or_key}")
    _safe_print(f"  OpenRouter usable      : {or_usable}")
    _safe_print()

    # Ollama
    ollama_ok = "yes" if health.ollama_reachable else "no"
    _safe_print(f"  Ollama reachable       : {ollama_ok}")
    if health.ollama_host_used:
        _safe_print(f"  Ollama host used       : {health.ollama_host_used}")
    if health.ollama_models:
        models_str = ", ".join(health.ollama_models[:8])
        if len(health.ollama_models) > 8:
            models_str += f" (+{len(health.ollama_models) - 8} more)"
        _safe_print(f"  Ollama models          : {models_str}")
    else:
        _safe_print("  Ollama models          : none / unknown")
    _safe_print()

    # Summary
    _safe_print(f"  Default provider       : {health.default_provider}")
    _safe_print(f"  Fallback provider      : {health.fallback_provider}")
    _safe_print(f"  Final status           : {health.status}")
    _safe_print()

    if health.hints:
        _safe_print("  Hints:")
        for hint in health.hints:
            for line in _wrap(hint, 56):
                _safe_print(f"    {line}")
        _safe_print()

    _safe_print("=" * 60)
    _safe_print()


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
        description="Check LLM provider availability for Bea."
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
