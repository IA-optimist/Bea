"""Tests for core/evaluation/model_role_benchmark.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.evaluation.model_role_benchmark import (
    _MOCK_RESPONSE,
    _check_ollama,
    _check_openrouter,
    _parse_sections,
    _skipped,
    run_benchmark,
    score_response,
)


# ── score_response ───────────────────────────────────────────────────────────

class TestScoreResponse:
    def test_perfect_response(self):
        ev = score_response(_MOCK_RESPONSE)
        assert ev["artifact_ok"] is True
        assert ev["syntax_valid"] is True
        assert ev["test_proof"] is True
        assert ev["score"] == 1.0
        assert ev["error_category"] is None

    def test_missing_sections(self):
        ev = score_response("Just some prose with no sections.")
        assert ev["artifact_ok"] is False
        assert ev["syntax_valid"] is False
        assert ev["score"] < 0.5
        assert ev["error_category"] == "artifact_invalid"

    def test_syntax_error_in_artifact(self):
        bad = "=== sha256_file.py ===\ndef broken(\n=== test_sha256_file.py ===\ndef test_sha256_file():\n    pass\n"
        ev = score_response(bad)
        assert ev["artifact_ok"] is True
        assert ev["syntax_valid"] is False
        assert ev["error_category"] == "syntax_error"

    def test_test_proof_detection(self):
        text = "=== sha256_file.py ===\ndef sha256_file(p): return ''\n"
        ev = score_response(text)
        assert ev["test_proof"] is False

    def test_score_partial(self):
        # artifact_ok and syntax_valid but no test
        text = "=== sha256_file.py ===\ndef sha256_file(p): return ''\n"
        ev = score_response(text)
        assert ev["artifact_ok"] is True
        assert ev["syntax_valid"] is True
        assert ev["test_proof"] is False
        assert round(ev["score"], 4) == round(2 / 3, 4)


class TestParseSections:
    def test_two_sections(self):
        sections = _parse_sections(_MOCK_RESPONSE)
        assert "sha256_file.py" in sections
        assert "test_sha256_file.py" in sections
        assert "def sha256_file" in sections["sha256_file.py"]
        assert "def test_sha256_file" in sections["test_sha256_file.py"]

    def test_empty_input(self):
        assert _parse_sections("") == {}

    def test_no_sections(self):
        assert _parse_sections("just prose") == {}


# ── Mock mode ────────────────────────────────────────────────────────────────

class TestMockMode:
    def test_mock_returns_passed(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert report["mode"] == "mock"
        assert len(report["results"]) == 1
        r = report["results"][0]
        assert r["passed"] is True
        assert r["success"] is True
        assert r["score"] == 1.0

    def test_mock_both_providers(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter", "ollama"], mock=True)
        assert len(report["results"]) == 2
        assert all(r["passed"] for r in report["results"])

    def test_mock_no_api_key_in_output(self):
        fake_key = "sk-or-v1-fakekey1234567890abcdefghijklmnop"
        report = run_benchmark(
            role="forge-builder",
            providers=["openrouter"],
            mock=True,
            openrouter_api_key=fake_key,
        )
        report_str = json.dumps(report)
        assert fake_key not in report_str

    def test_mock_model_is_mock(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert report["results"][0]["model_used"] == "mock-model"


# ── Provider health check (mocked network) ───────────────────────────────────

class TestProviderHealthChecks:
    def test_openrouter_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_openrouter("sk-or-v1-validkey123456789012345678901") is True

    def test_openrouter_short_key(self):
        assert _check_openrouter("short") is False

    def test_openrouter_empty_key(self):
        assert _check_openrouter("") is False

    def test_openrouter_unreachable(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            assert _check_openrouter("sk-or-v1-validkey123456789012345678901") is False

    def test_ollama_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _check_ollama() is True

    def test_ollama_unreachable(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no ollama")):
            assert _check_ollama() is False


# ── Real mode — skipping unavailable providers ────────────────────────────────

class TestRealModeProviderSkipping:
    def test_openrouter_unavailable_is_skipped(self):
        with patch(
            "core.evaluation.model_role_benchmark._check_openrouter",
            return_value=False,
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="",
            )
        assert len(report["results"]) == 1
        r = report["results"][0]
        assert r["skipped"] is True
        assert r["skip_reason"] == "provider_unavailable"
        assert r["provider_used"] == "openrouter"

    def test_ollama_unavailable_is_skipped(self):
        with patch(
            "core.evaluation.model_role_benchmark._check_ollama",
            return_value=False,
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["ollama"],
                mock=False,
            )
        assert len(report["results"]) == 1
        r = report["results"][0]
        assert r["skipped"] is True
        assert r["skip_reason"] == "provider_unavailable"
        assert r["provider_used"] == "ollama"

    def test_unknown_provider_is_skipped(self):
        report = run_benchmark(
            role="forge-builder",
            providers=["unknown_provider"],
            mock=False,
        )
        r = report["results"][0]
        assert r["skipped"] is True
        assert "unknown_provider" in r["skip_reason"]

    def test_all_skipped_still_returns_results_list(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=False),
            patch("core.evaluation.model_role_benchmark._check_ollama", return_value=False),
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["openrouter", "ollama"],
                mock=False,
            )
        assert len(report["results"]) == 2
        assert all(r["skipped"] for r in report["results"])


# ── Real mode — successful mocked LLM calls ──────────────────────────────────

class TestRealModeSuccess:
    def test_openrouter_pass(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_openrouter",
                return_value=_MOCK_RESPONSE,
            ),
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["skipped"] is False
        assert r["passed"] is True
        assert r["score"] == 1.0
        assert r["provider_used"] == "openrouter"
        assert "sk-or-v1" not in json.dumps(report)

    def test_ollama_pass(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_ollama", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_ollama",
                return_value=_MOCK_RESPONSE,
            ),
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["ollama"],
                mock=False,
            )
        r = report["results"][0]
        assert r["skipped"] is False
        assert r["passed"] is True
        assert r["provider_used"] == "ollama"

    def test_openrouter_llm_error_does_not_raise(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_openrouter",
                side_effect=Exception("connection reset"),
            ),
        ):
            report = run_benchmark(
                role="forge-builder",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["skipped"] is False
        assert r["success"] is False
        assert r["error_category"] == "Exception"


# ── Score/success/passed coherence ───────────────────────────────────────────

class TestCoherence:
    def test_passed_requires_success(self):
        skipped = _skipped("forge-builder", "openrouter", "test")
        assert skipped.passed is False
        assert skipped.success is False

    def test_score_zero_means_not_passed(self):
        report = run_benchmark(
            role="forge-builder",
            providers=["openrouter"],
            mock=False,
            openrouter_api_key="",
        )
        for r in report["results"]:
            if r.get("skipped"):
                assert r["score"] == 0.0

    def test_report_structure(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert "mode" in report
        assert "role" in report
        assert "results" in report
        r = report["results"][0]
        required_keys = {
            "role", "provider_used", "model_used", "success", "passed",
            "score", "duration_s", "artifact_ok", "syntax_valid",
            "test_proof", "fallback_used", "error_category", "skipped",
        }
        assert required_keys.issubset(r.keys())
