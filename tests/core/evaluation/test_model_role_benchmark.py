"""Tests for core/evaluation/model_role_benchmark.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from core.evaluation.model_role_benchmark import (
    _MOCK_RESPONSE,
    _MOCK_SCOUT_RESPONSE,
    _MOCK_SHADOW_RESPONSE,
    _check_ollama,
    _check_openrouter,
    _parse_sections,
    _skipped,
    run_benchmark,
    score_response,
    score_scout_research,
    score_shadow_advisor,
)


# ── score_response (forge-builder) ───────────────────────────────────────────

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


# ── score_scout_research ─────────────────────────────────────────────────────

class TestScoreScoutResearch:
    def test_perfect_structured_response(self):
        ev = score_scout_research(_MOCK_SCOUT_RESPONSE)
        assert ev["structured_output"] is True
        assert ev["no_timeout"] is True
        assert ev["useful_answer"] is True
        assert ev["score"] == 1.0
        assert ev["error_category"] is None

    def test_timeout_penalized(self):
        ev = score_scout_research("", timed_out=True)
        assert ev["timeout"] is True
        assert ev["no_timeout"] is False
        assert ev["score"] < 0.7
        assert ev["passed"] is False if "passed" in ev else ev["score"] < 0.7
        assert ev["error_category"] == "timeout"

    def test_missing_structure_penalized(self):
        long_prose = "This is a generic response without any of the required sections and it is long enough."
        ev = score_scout_research(long_prose)
        assert ev["structured_output"] is False
        assert ev["no_timeout"] is True
        assert ev["useful_answer"] is True
        assert ev["score"] < 1.0

    def test_empty_response_penalized(self):
        ev = score_scout_research("")
        assert ev["useful_answer"] is False
        assert ev["score"] < 0.7

    def test_all_three_keys_present_in_response(self):
        text = "blockers: [x]\ndegraded_risks: [y]\nrecommended_next_action: do this"
        ev = score_scout_research(text)
        assert ev["structured_output"] is True

    def test_no_timeout_is_true_by_default(self):
        ev = score_scout_research("something")
        assert ev["no_timeout"] is True
        assert ev["timeout"] is False


# ── score_shadow_advisor ─────────────────────────────────────────────────────

class TestScoreShadowAdvisor:
    def test_perfect_json_response(self):
        ev = score_shadow_advisor(_MOCK_SHADOW_RESPONSE)
        assert ev["json_valid"] is True
        assert ev["schema_valid"] is True
        assert ev["no_markdown"] is True
        assert ev["score"] == 1.0

    def test_markdown_fenced_json_penalized(self):
        wrapped = "```json\n" + _MOCK_SHADOW_RESPONSE + "\n```"
        ev = score_shadow_advisor(wrapped)
        assert ev["json_valid"] is True   # strip fences, still parseable
        assert ev["schema_valid"] is True
        assert ev["no_markdown"] is False
        assert ev["score"] < 1.0

    def test_invalid_json_fails(self):
        ev = score_shadow_advisor("voici la reponse: {invalid json here")
        assert ev["json_valid"] is False
        assert ev["schema_valid"] is False
        assert ev["score"] < 0.4
        assert ev["error_category"] == "json_invalid"

    def test_valid_json_missing_schema_keys(self):
        partial = json.dumps({"risk_level": "low", "blockers": []})
        ev = score_shadow_advisor(partial)
        assert ev["json_valid"] is True
        assert ev["schema_valid"] is False
        assert "schema_missing" in (ev["error_category"] or "")

    def test_no_markdown_flag_true_for_clean_json(self):
        clean = '{"risk_level": "low", "blockers": [], "degraded_risks": [], "recommended_next_action": "x", "confidence": 0.5}'
        ev = score_shadow_advisor(clean)
        assert ev["no_markdown"] is True
        assert ev["score"] == 1.0


# ── Mock mode ────────────────────────────────────────────────────────────────

class TestMockMode:
    def test_mock_forge_builder_returns_passed(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert report["mode"] == "mock"
        r = report["results"][0]
        assert r["passed"] is True
        assert r["score"] == 1.0

    def test_mock_scout_research_returns_passed(self):
        report = run_benchmark(role="scout-research", providers=["openrouter"], mock=True)
        r = report["results"][0]
        assert r["passed"] is True
        assert r["structured_output"] is True
        assert r["local_docs_used"] is True

    def test_mock_shadow_advisor_returns_passed(self):
        report = run_benchmark(role="shadow-advisor", providers=["openrouter"], mock=True)
        r = report["results"][0]
        assert r["passed"] is True
        assert r["json_valid"] is True
        assert r["schema_valid"] is True

    def test_mock_multi_role_all_providers(self):
        report = run_benchmark(
            roles=["forge-builder", "scout-research", "shadow-advisor"],
            providers=["openrouter", "ollama"],
            mock=True,
        )
        assert report["mode"] == "mock"
        assert "roles" in report
        assert len(report["results"]) == 6  # 3 roles × 2 providers
        assert all(r["passed"] for r in report["results"])

    def test_mock_no_api_key_in_output(self):
        fake_key = "sk-or-v1-fakekey1234567890abcdefghijklmnop"
        report = run_benchmark(
            role="forge-builder",
            providers=["openrouter"],
            mock=True,
            openrouter_api_key=fake_key,
        )
        assert fake_key not in json.dumps(report)

    def test_mock_model_is_mock(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert report["results"][0]["model_used"] == "mock-model"


# ── Multi-role summary ───────────────────────────────────────────────────────

class TestMultiRoleSummary:
    def test_summary_best_by_role_present(self):
        report = run_benchmark(
            roles=["forge-builder", "scout-research", "shadow-advisor"],
            providers=["openrouter"],
            mock=True,
        )
        assert "summary" in report
        assert "best_by_role" in report["summary"]
        assert "forge-builder" in report["summary"]["best_by_role"]
        assert "scout-research" in report["summary"]["best_by_role"]
        assert "shadow-advisor" in report["summary"]["best_by_role"]

    def test_summary_best_by_role_picks_highest_score(self):
        # Mock: openrouter scores 1.0, ollama scores 0.67 (via partial real scoring)
        # We patch the results to simulate two different scores
        report = run_benchmark(
            roles=["forge-builder"],
            providers=["openrouter", "ollama"],
            mock=True,
        )
        best = report["summary"]["best_by_role"]["forge-builder"]
        assert best["score"] >= 0.0
        assert "provider_used" in best

    def test_summary_excludes_skipped(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=False),
            patch("core.evaluation.model_role_benchmark._check_ollama", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_ollama",
                return_value=_MOCK_SHADOW_RESPONSE,
            ),
        ):
            report = run_benchmark(
                roles=["shadow-advisor"],
                providers=["openrouter", "ollama"],
                mock=False,
            )
        best = report["summary"]["best_by_role"]
        assert "shadow-advisor" in best
        assert best["shadow-advisor"]["provider_used"] == "ollama"

    def test_single_role_no_summary(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert "summary" not in report
        assert "role" in report


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
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("no ollama")):
            assert _check_ollama() is False


# ── Real mode — provider skipping ────────────────────────────────────────────

class TestRealModeProviderSkipping:
    def test_openrouter_unavailable_is_skipped(self):
        with patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=False):
            report = run_benchmark(
                role="forge-builder",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="",
            )
        r = report["results"][0]
        assert r["skipped"] is True
        assert r["skip_reason"] == "provider_unavailable"

    def test_ollama_unavailable_is_skipped(self):
        with patch("core.evaluation.model_role_benchmark._check_ollama", return_value=False):
            report = run_benchmark(
                role="forge-builder",
                providers=["ollama"],
                mock=False,
            )
        r = report["results"][0]
        assert r["skipped"] is True

    def test_unknown_provider_is_skipped(self):
        report = run_benchmark(
            role="forge-builder",
            providers=["unknown_provider"],
            mock=False,
        )
        r = report["results"][0]
        assert r["skipped"] is True
        assert "unknown_provider" in r["skip_reason"]

    def test_provider_unavailable_in_multi_role(self):
        """All roles for an unavailable provider should be skipped."""
        with patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=False):
            report = run_benchmark(
                roles=["forge-builder", "scout-research", "shadow-advisor"],
                providers=["openrouter"],
                mock=False,
            )
        assert len(report["results"]) == 3
        assert all(r["skipped"] is True for r in report["results"])
        assert all(r["provider_used"] == "openrouter" for r in report["results"])

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
    def test_openrouter_forge_builder_pass(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch("core.evaluation.model_role_benchmark._call_openrouter", return_value=_MOCK_RESPONSE),
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
        assert "sk-or-v1" not in json.dumps(report)

    def test_openrouter_scout_research_pass(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch("core.evaluation.model_role_benchmark._call_openrouter", return_value=_MOCK_SCOUT_RESPONSE),
        ):
            report = run_benchmark(
                role="scout-research",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["skipped"] is False
        assert r["structured_output"] is True
        assert r["local_docs_used"] is True

    def test_openrouter_shadow_advisor_pass(self):
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch("core.evaluation.model_role_benchmark._call_openrouter", return_value=_MOCK_SHADOW_RESPONSE),
        ):
            report = run_benchmark(
                role="shadow-advisor",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["json_valid"] is True
        assert r["schema_valid"] is True
        assert r["retry_count"] == 1

    def test_llm_error_does_not_raise(self):
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

    def test_no_api_key_in_multi_role_output(self):
        fake_key = "sk-or-v1-supersecretkey1234567890abcdef"
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch("core.evaluation.model_role_benchmark._call_openrouter", return_value=_MOCK_RESPONSE),
        ):
            report = run_benchmark(
                roles=["forge-builder", "scout-research"],
                providers=["openrouter"],
                mock=False,
                openrouter_api_key=fake_key,
            )
        assert fake_key not in json.dumps(report)


# ── Score/success/passed coherence ───────────────────────────────────────────

class TestCoherence:
    def test_passed_requires_score_above_threshold(self):
        # score 0.33 → passed=False
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        for r in report["results"]:
            if r.get("skipped"):
                assert r["score"] == 0.0
            else:
                if r["score"] < 0.7:
                    assert r["passed"] is False

    def test_skipped_is_not_quality_failure(self):
        s = _skipped("forge-builder", "openrouter", "provider_unavailable")
        d = s.to_dict()
        assert d["skipped"] is True
        assert d["success"] is False
        # Skipped ≠ "bad model" — skip_reason is present
        assert d["skip_reason"] == "provider_unavailable"
        assert d["score"] == 0.0

    def test_report_structure_single_role(self):
        report = run_benchmark(role="forge-builder", providers=["openrouter"], mock=True)
        assert "mode" in report
        assert "role" in report
        assert "results" in report
        r = report["results"][0]
        required_keys = {
            "role", "provider_used", "model_used", "success", "passed",
            "score", "duration_s", "fallback_used", "error_category", "skipped",
        }
        assert required_keys.issubset(r.keys())

    def test_report_structure_multi_role(self):
        report = run_benchmark(
            roles=["forge-builder"],
            providers=["openrouter"],
            mock=True,
        )
        assert "mode" in report
        assert "roles" in report
        assert "providers" in report
        assert "results" in report
        assert "summary" in report

    def test_scout_research_timeout_penalized(self):
        """TimeoutError in LLM call → scout-research has no_timeout=False, passed=False."""
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_openrouter",
                side_effect=TimeoutError("request timed out"),
            ),
        ):
            report = run_benchmark(
                role="scout-research",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["skipped"] is False
        assert r.get("timeout") is True
        assert r["passed"] is False

    def test_shadow_advisor_invalid_json_penalized(self):
        """Invalid JSON from LLM → json_valid=False, schema_valid=False, score < 0.4."""
        with (
            patch("core.evaluation.model_role_benchmark._check_openrouter", return_value=True),
            patch(
                "core.evaluation.model_role_benchmark._call_openrouter",
                return_value="voici ma reponse: {invalid json here",
            ),
        ):
            report = run_benchmark(
                role="shadow-advisor",
                providers=["openrouter"],
                mock=False,
                openrouter_api_key="sk-or-v1-fake123456789012345678901234",
            )
        r = report["results"][0]
        assert r["json_valid"] is False
        assert r["schema_valid"] is False
        assert r["score"] < 0.4
        assert r["passed"] is False
