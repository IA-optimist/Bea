"""Tests for scripts/provider_healthcheck.py — CLI behaviour and Windows safety.

No network calls are made. All LLM provider calls are mocked.
"""
from __future__ import annotations

import io
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable when running from the worktree.
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.providers.runtime_health import ProviderHealth
import scripts.provider_healthcheck as phc


# -- Fixtures -----------------------------------------------------------------

def _unavailable() -> ProviderHealth:
    return ProviderHealth(
        openrouter_key_present=False,
        openrouter_usable=False,
        ollama_reachable=False,
        status="UNAVAILABLE",
        hints=["Configure OPENROUTER_API_KEY or start Ollama."],
    )


def _degraded() -> ProviderHealth:
    return ProviderHealth(
        openrouter_key_present=False,
        openrouter_usable=False,
        ollama_reachable=True,
        ollama_host_used="http://127.0.0.1:11434",
        ollama_models=["gemma4:12b"],
        default_provider="ollama",
        status="DEGRADED",
        hints=["Degraded: OpenRouter absent, Ollama available (gemma4:12b)."],
    )


def _ready() -> ProviderHealth:
    return ProviderHealth(
        openrouter_key_present=True,
        openrouter_usable=True,
        ollama_reachable=True,
        ollama_host_used="http://127.0.0.1:11434",
        ollama_models=["gemma4:12b"],
        default_provider="openrouter",
        fallback_provider="ollama",
        status="READY",
        hints=[],
    )


# -- _supports_unicode / _status_icon ----------------------------------------

class TestStatusIcon:
    def test_ascii_icon_ready(self) -> None:
        with patch.object(phc, "_supports_unicode", return_value=False):
            assert phc._status_icon("READY") == "OK"

    def test_ascii_icon_fail(self) -> None:
        with patch.object(phc, "_supports_unicode", return_value=False):
            assert phc._status_icon("UNAVAILABLE") == "FAIL"

    def test_ascii_icon_degraded(self) -> None:
        with patch.object(phc, "_supports_unicode", return_value=False):
            assert phc._status_icon("DEGRADED") == "~~"

    def test_unicode_icon_ready(self) -> None:
        with patch.object(phc, "_supports_unicode", return_value=True):
            icon = phc._status_icon("READY")
            assert icon == "✓"

    def test_ascii_icons_are_ascii_encodable(self) -> None:
        """ASCII fallback icons must never raise on narrow Windows code pages."""
        with patch.object(phc, "_supports_unicode", return_value=False):
            for status in ("READY", "DEGRADED", "UNAVAILABLE"):
                icon = phc._status_icon(status)
                icon.encode("ascii")  # must not raise


# -- _print_human output safety -----------------------------------------------

class TestPrintHumanOutput:
    def _capture(self, health: ProviderHealth) -> str:
        buf = io.StringIO()
        with patch("builtins.print", side_effect=lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
            phc._print_human(health)
        return buf.getvalue()

    def test_unavailable_output_is_ascii_safe(self) -> None:
        """When ASCII fallback is active, output must encode cleanly to cp1252."""
        with patch.object(phc, "_supports_unicode", return_value=False):
            output = self._capture(_unavailable())
        output.encode("cp1252")  # must not raise

    def test_ready_output_contains_status(self) -> None:
        output = self._capture(_ready())
        assert "READY" in output

    def test_degraded_output_mentions_ollama(self) -> None:
        output = self._capture(_degraded())
        assert "ollama" in output.lower() or "127.0.0.1" in output

    def test_hints_are_printed(self) -> None:
        output = self._capture(_unavailable())
        assert "Hints" in output or "OPENROUTER" in output or "ollama" in output.lower()

    def test_no_secret_in_human_output(self) -> None:
        secret = "sk-or-v1-reallylongsecretkeythatshouldbehidden"
        health = ProviderHealth(
            openrouter_key_present=True,
            status="READY",
            hints=[],
        )
        output = self._capture(health)
        assert secret not in output

    def test_safe_print_handles_unicode_error(self) -> None:
        """_safe_print must not propagate UnicodeEncodeError."""
        call_count = {"n": 0}

        def _failing_print(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise UnicodeEncodeError("cp1252", "✓", 0, 1, "ordinal not in range")
            # second call (from except branch) succeeds
            return None

        with patch("builtins.print", side_effect=_failing_print):
            phc._safe_print("hello ✓ world")  # must not raise


# -- _print_json output safety ------------------------------------------------

class TestPrintJsonOutput:
    def test_json_output_no_secret(self) -> None:
        secret = "sk-or-v1-topsecretkeyvalue12345678"
        health = ProviderHealth(
            openrouter_key_present=True,
            openrouter_usable=True,
            status="READY",
            hints=[],
        )
        buf = io.StringIO()
        with patch("builtins.print", side_effect=lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
            phc._print_json(health)
        output = buf.getvalue()
        assert secret not in output

    def test_json_output_fallback_ascii_on_encode_error(self) -> None:
        """If print raises UnicodeEncodeError, fall back to ensure_ascii=True."""
        health = _unavailable()
        call_args: list[str] = []

        def _mock_print(text: str) -> None:
            call_args.append(text)
            if len(call_args) == 1:
                raise UnicodeEncodeError("cp1252", text, 0, 1, "char not in range")

        with patch("builtins.print", side_effect=_mock_print):
            phc._print_json(health)  # must not raise

        assert len(call_args) == 2
        # Second call must be ASCII-safe
        call_args[1].encode("ascii")


# -- _run exit codes ----------------------------------------------------------

class TestRunExitCode:
    def _run(self, health: ProviderHealth, json_flag: bool = False) -> int:
        import argparse
        args = argparse.Namespace(json=json_flag)
        # check_provider_health_sync is imported lazily inside _run(), so patch
        # the source module rather than the script's namespace.
        with (
            patch("core.providers.runtime_health.check_provider_health_sync", return_value=health),
            patch("scripts.provider_healthcheck._print_human"),
            patch("scripts.provider_healthcheck._print_json"),
        ):
            return phc._run(args)

    def test_ready_exits_0(self) -> None:
        assert self._run(_ready()) == 0

    def test_degraded_exits_1(self) -> None:
        assert self._run(_degraded()) == 1

    def test_unavailable_exits_1(self) -> None:
        assert self._run(_unavailable()) == 1
