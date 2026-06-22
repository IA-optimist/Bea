"""Tests for core/evaluation/routing_advisor.py."""
from __future__ import annotations

import json

import pytest

from core.evaluation.routing_advisor import build_advisory_report, compute_advice


# ── Helpers ───────────────────────────────────────────────────────────────────

def _r(role: str, provider: str, score: float, passed: bool, *, skipped: bool = False,
        duration_s: float = 10.0, model: str = "test-model",
        skip_reason: str | None = None, error_category: str | None = None) -> dict:
    return {
        "role": role,
        "provider_used": provider,
        "model_used": model,
        "score": score,
        "passed": passed,
        "success": passed or (not skipped and score > 0),
        "skipped": skipped,
        "skip_reason": skip_reason,
        "duration_s": duration_s,
        "error_category": error_category,
    }


# ── Forge-builder ────────────────────────────────────────────────────────────

class TestForgeBuilder:
    def test_recommends_openrouter_when_ollama_failed(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True, duration_s=18.0, model="gpt-oss-120b:free"),
            _r("forge-builder", "ollama", 0.0, False, duration_s=40.0, model="gemma4:12b",
               error_category="artifact_invalid"),
        ]
        advice = compute_advice(results)
        assert advice["forge-builder"]["preferred_provider"] == "openrouter"
        assert advice["forge-builder"]["preferred_model"] == "gpt-oss-120b:free"
        assert advice["forge-builder"]["passed_count"] == 1
        assert advice["forge-builder"]["failed_count"] == 1
        assert advice["forge-builder"]["skipped_count"] == 0

    def test_runtime_enforced_false(self):
        results = [_r("forge-builder", "openrouter", 1.0, True)]
        advice = compute_advice(results)
        assert advice["forge-builder"]["runtime_enforced"] is False

    def test_confidence_is_low(self):
        results = [_r("forge-builder", "openrouter", 1.0, True)]
        advice = compute_advice(results)
        assert advice["forge-builder"]["confidence"] == "low"


# ── Scout-research ────────────────────────────────────────────────────────────

class TestScoutResearch:
    def test_tie_broken_by_duration(self):
        results = [
            _r("scout-research", "openrouter", 1.0, True, duration_s=12.0),
            _r("scout-research", "ollama", 1.0, True, duration_s=45.0),
        ]
        advice = compute_advice(results)
        # OpenRouter is faster
        assert advice["scout-research"]["preferred_provider"] == "openrouter"
        assert advice["scout-research"]["passed_count"] == 2
        assert advice["scout-research"]["failed_count"] == 0

    def test_reason_mentions_faster_when_tied(self):
        results = [
            _r("scout-research", "openrouter", 1.0, True, duration_s=12.0),
            _r("scout-research", "ollama", 1.0, True, duration_s=45.0),
        ]
        advice = compute_advice(results)
        reason = advice["scout-research"]["reason"].lower()
        assert "faster" in reason or "duration" in reason

    def test_ollama_wins_when_faster_and_tied(self):
        results = [
            _r("scout-research", "openrouter", 1.0, True, duration_s=60.0),
            _r("scout-research", "ollama", 1.0, True, duration_s=10.0),
        ]
        advice = compute_advice(results)
        assert advice["scout-research"]["preferred_provider"] == "ollama"


# ── Shadow-advisor ────────────────────────────────────────────────────────────

class TestShadowAdvisor:
    def test_recommends_openrouter_when_json_invalid(self):
        results = [
            _r("shadow-advisor", "openrouter", 1.0, True),
            _r("shadow-advisor", "ollama", 0.33, False, error_category="json_invalid"),
        ]
        advice = compute_advice(results)
        assert advice["shadow-advisor"]["preferred_provider"] == "openrouter"
        assert advice["shadow-advisor"]["passed_count"] == 1
        assert advice["shadow-advisor"]["failed_count"] == 1

    def test_no_pass_picks_highest_score(self):
        results = [
            _r("shadow-advisor", "openrouter", 0.5, False),
            _r("shadow-advisor", "ollama", 0.33, False),
        ]
        advice = compute_advice(results)
        assert advice["shadow-advisor"]["preferred_provider"] == "openrouter"
        assert advice["shadow-advisor"]["passed_count"] == 0
        assert "did not pass" in advice["shadow-advisor"]["reason"]


# ── Skipped providers ─────────────────────────────────────────────────────────

class TestSkippedProviders:
    def test_skipped_not_counted_as_failed(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True, skipped=False),
            _r("forge-builder", "ollama", 0.0, False, skipped=True, skip_reason="provider_unavailable"),
        ]
        advice = compute_advice(results)
        assert advice["forge-builder"]["failed_count"] == 0
        assert advice["forge-builder"]["skipped_count"] == 1
        assert advice["forge-builder"]["passed_count"] == 1

    def test_all_skipped_returns_null_recommendation(self):
        results = [
            _r("shadow-advisor", "openrouter", 0.0, False, skipped=True, skip_reason="provider_unavailable"),
            _r("shadow-advisor", "ollama", 0.0, False, skipped=True, skip_reason="provider_unavailable"),
        ]
        advice = compute_advice(results)
        assert advice["shadow-advisor"]["preferred_provider"] is None
        assert advice["shadow-advisor"]["reason"] == "all_providers_skipped"
        assert advice["shadow-advisor"]["skipped_count"] == 2
        assert advice["shadow-advisor"]["failed_count"] == 0

    def test_one_skipped_one_passed(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True, skipped=False),
            _r("forge-builder", "ollama", 0.0, False, skipped=True),
        ]
        advice = compute_advice(results)
        assert advice["forge-builder"]["preferred_provider"] == "openrouter"
        assert advice["forge-builder"]["skipped_count"] == 1
        assert advice["forge-builder"]["failed_count"] == 0


# ── Invariants ────────────────────────────────────────────────────────────────

class TestInvariants:
    def test_runtime_enforced_always_false_multi_role(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True),
            _r("scout-research", "openrouter", 1.0, True),
            _r("shadow-advisor", "openrouter", 1.0, True),
        ]
        advice = compute_advice(results)
        for role_advice in advice.values():
            assert role_advice["runtime_enforced"] is False

    def test_confidence_never_high(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True),
            _r("scout-research", "ollama", 1.0, True),
        ]
        advice = compute_advice(results)
        for role_advice in advice.values():
            assert role_advice["confidence"] not in ("high", "definitive", "certain", "medium")

    def test_no_api_key_in_output(self):
        results = [_r("forge-builder", "openrouter", 1.0, True, model="gpt-oss-120b:free")]
        advice = compute_advice(results)
        output = json.dumps(advice)
        assert "sk-or-v1" not in output
        assert "Bearer " not in output
        assert "OPENROUTER_API_KEY" not in output

    def test_empty_results_returns_empty_advice(self):
        advice = compute_advice([])
        assert advice == {}


# ── build_advisory_report ─────────────────────────────────────────────────────

class TestBuildAdvisoryReport:
    def test_report_structure(self):
        results = [_r("forge-builder", "openrouter", 1.0, True)]
        report = build_advisory_report(results, source_file="test.json")
        assert report["mode"] == "advisory"
        assert report["source_file"] == "test.json"
        assert "generated_at" in report
        assert "caveat" in report
        assert "recommendations" in report
        assert "forge-builder" in report["recommendations"]

    def test_report_caveat_mentions_informational(self):
        report = build_advisory_report([_r("forge-builder", "openrouter", 1.0, True)])
        assert "informational" in report["caveat"].lower() or "Informational" in report["caveat"]

    def test_report_runtime_enforced_false(self):
        results = [
            _r("forge-builder", "openrouter", 1.0, True),
            _r("shadow-advisor", "ollama", 0.33, False),
        ]
        report = build_advisory_report(results)
        for rec in report["recommendations"].values():
            assert rec["runtime_enforced"] is False

    def test_no_api_key_in_report(self):
        results = [_r("forge-builder", "openrouter", 1.0, True)]
        report = build_advisory_report(results, source_file="workspace/test.json")
        report_str = json.dumps(report)
        assert "sk-or-v1" not in report_str
        assert "Bearer " not in report_str

    def test_real_world_fixture(self):
        """Fixture matching actual PR #99 benchmark results."""
        results = [
            _r("forge-builder", "openrouter", 1.0, True, duration_s=14.0, model="gpt-oss-120b:free"),
            _r("forge-builder", "ollama", 0.0, False, duration_s=40.0, model="gemma4:12b",
               error_category="artifact_invalid"),
            _r("scout-research", "openrouter", 1.0, True, duration_s=12.0, model="gpt-oss-120b:free"),
            _r("scout-research", "ollama", 1.0, True, duration_s=45.0, model="gemma4:12b"),
            _r("shadow-advisor", "openrouter", 1.0, True, duration_s=8.0, model="gpt-oss-120b:free"),
            _r("shadow-advisor", "ollama", 0.33, False, duration_s=35.0, model="gemma4:12b",
               error_category="json_invalid"),
        ]
        report = build_advisory_report(results, source_file="workspace/model_role_benchmark_multi_role.json")
        recs = report["recommendations"]

        assert recs["forge-builder"]["preferred_provider"] == "openrouter"
        assert recs["scout-research"]["preferred_provider"] == "openrouter"  # faster
        assert recs["shadow-advisor"]["preferred_provider"] == "openrouter"

        for rec in recs.values():
            assert rec["runtime_enforced"] is False
            assert rec["confidence"] == "low"
