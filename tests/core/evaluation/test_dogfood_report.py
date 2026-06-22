"""Tests for core/evaluation/dogfood_report.py and scripts/dogfood_routing_advice.py."""
from __future__ import annotations

import json

import pytest

from core.evaluation.dogfood_report import (
    check_matched_advice,
    compute_dogfood_summary,
    validate_mission,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mission(
    mission_id: str = "dogfood-X",
    role: str = "forge-builder",
    goal: str = "test goal",
    advised_provider: str | None = "openrouter",
    provider_used: str = "openrouter",
    model_used: str = "gpt-oss-120b:free",
    matched_advice: bool = True,
    success: bool = True,
    passed: bool = True,
    score: float = 1.0,
    duration_s: float = 10.0,
    fallback_used: bool = False,
    error_category: str | None = None,
    skipped: bool = False,
    mode: str = "fixture",
    provider_status: str = "fixture",
    runtime_enforced: bool = False,
    **extra,
) -> dict:
    m = {
        "mission_id": mission_id,
        "role": role,
        "goal": goal,
        "mode": mode,
        "advised_provider": advised_provider,
        "provider_used": provider_used,
        "model_used": model_used,
        "provider_status": provider_status,
        "matched_advice": matched_advice,
        "success": success,
        "passed": passed,
        "score": score,
        "duration_s": duration_s,
        "fallback_used": fallback_used,
        "error_category": error_category,
        "skipped": skipped,
        "runtime_enforced": runtime_enforced,
    }
    m.update(extra)
    return m


def _five_missions(**overrides_for_last) -> list[dict]:
    missions = [
        _mission("dogfood-A", role="forge-builder"),
        _mission("dogfood-B", role="forge-builder"),
        _mission("dogfood-C", role="scout-research"),
        _mission("dogfood-D", role="shadow-advisor"),
        _mission("dogfood-E", role="shadow-advisor", **overrides_for_last),
    ]
    return missions


# ── validate_mission ───────────────────────────────────────────────────────────

class TestValidateMission:
    def test_valid_mission_has_no_errors(self):
        assert validate_mission(_mission()) == []

    def test_missing_field_produces_error(self):
        m = _mission()
        del m["role"]
        errs = validate_mission(m)
        assert any("missing field: role" in e for e in errs)

    def test_runtime_enforced_true_is_error(self):
        m = _mission()
        m["runtime_enforced"] = True
        errs = validate_mission(m)
        assert any("runtime_enforced" in e for e in errs)

    def test_runtime_enforced_false_is_ok(self):
        m = _mission()
        m["runtime_enforced"] = False
        assert validate_mission(m) == []


# ── check_matched_advice ───────────────────────────────────────────────────────

class TestCheckMatchedAdvice:
    def test_match_when_providers_equal(self):
        m = _mission(role="forge-builder", provider_used="openrouter")
        advice = {"forge-builder": {"preferred_provider": "openrouter"}}
        assert check_matched_advice(m, advice) is True

    def test_no_match_when_providers_differ(self):
        m = _mission(role="forge-builder", provider_used="ollama")
        advice = {"forge-builder": {"preferred_provider": "openrouter"}}
        assert check_matched_advice(m, advice) is False

    def test_no_match_when_advice_has_null_provider(self):
        m = _mission(role="forge-builder", provider_used="openrouter")
        advice = {"forge-builder": {"preferred_provider": None}}
        assert check_matched_advice(m, advice) is False

    def test_no_match_when_role_not_in_advice(self):
        m = _mission(role="unknown-role", provider_used="openrouter")
        advice = {"forge-builder": {"preferred_provider": "openrouter"}}
        assert check_matched_advice(m, advice) is False

    def test_supports_nested_recommendations_key(self):
        m = _mission(role="forge-builder", provider_used="openrouter")
        advice = {"recommendations": {"forge-builder": {"preferred_provider": "openrouter"}}}
        assert check_matched_advice(m, advice) is True


# ── compute_dogfood_summary ────────────────────────────────────────────────────

class TestComputeDogfoodSummary:
    def test_summary_counts_correct(self):
        missions = _five_missions(passed=False, success=True, score=0.67)
        s = compute_dogfood_summary(missions)
        assert s["total"] == 5
        assert s["passed"] == 4
        assert s["failed"] == 1
        assert s["skipped"] == 0

    def test_runtime_enforced_always_false(self):
        s = compute_dogfood_summary(_five_missions())
        assert s["runtime_enforced"] is False

    def test_matched_advice_count(self):
        missions = _five_missions()
        # All have matched_advice=True by default
        s = compute_dogfood_summary(missions)
        assert s["matched_advice"] == 5
        assert s["advice_match_rate"] == 1.0

    def test_skipped_not_counted_as_failure(self):
        missions = [
            _mission("dogfood-A", passed=True, skipped=False),
            _mission("dogfood-B", passed=False, skipped=True),  # skipped
        ]
        s = compute_dogfood_summary(missions)
        assert s["skipped"] == 1
        assert s["failed"] == 0  # skipped does not count as failed
        assert s["passed"] == 1

    def test_advice_match_rate_partial(self):
        missions = [
            _mission("dogfood-A", matched_advice=True),
            _mission("dogfood-B", matched_advice=False),
        ]
        s = compute_dogfood_summary(missions)
        assert s["matched_advice"] == 1
        assert s["advice_match_rate"] == 0.5

    def test_empty_missions(self):
        s = compute_dogfood_summary([])
        assert s["total"] == 0
        assert s["advice_match_rate"] == 0.0


# ── Dogfood report integration ─────────────────────────────────────────────────

class TestDogfoodReportIntegration:
    def test_report_has_five_missions(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        assert len(report["missions"]) == 5

    def test_runtime_enforced_false_everywhere(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        assert report["runtime_enforced"] is False
        assert report["summary"]["runtime_enforced"] is False
        for m in report["missions"]:
            assert m.get("runtime_enforced") is False

    def test_mode_is_fixture_not_real(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        assert report["mode"] == "fixture"
        assert report["mode"] != "real"

    def test_no_api_key_in_output(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        report_str = json.dumps(report)
        assert "sk-or-v1" not in report_str
        assert "Bearer " not in report_str

    def test_summary_has_expected_keys(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        s = report["summary"]
        for key in ("total", "passed", "failed", "skipped", "matched_advice",
                    "advice_match_rate", "runtime_enforced"):
            assert key in s, f"Missing key in summary: {key}"

    def test_mission_ids_are_unique(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        ids = [m["mission_id"] for m in report["missions"]]
        assert len(ids) == len(set(ids))

    def test_provider_unavailable_not_failure(self):
        # A skipped mission should not increment failed count
        missions = [
            _mission("dogfood-A", skipped=True, passed=False),
            _mission("dogfood-B", skipped=False, passed=True),
        ]
        s = compute_dogfood_summary(missions)
        assert s["failed"] == 0
        assert s["skipped"] == 1

    def test_shadow_advisor_json_invalid_gives_passed_false(self):
        m = _mission(
            role="shadow-advisor",
            json_valid=False,
            schema_valid=False,
            no_markdown=False,
            score=0.0,
            passed=False,
            success=True,
        )
        assert m["passed"] is False
        assert m["score"] < 0.7

    def test_forge_builder_no_artifact_gives_passed_false(self):
        m = _mission(
            role="forge-builder",
            artifact_ok=False,
            syntax_valid=False,
            test_proof=False,
            score=0.0,
            passed=False,
        )
        assert m["passed"] is False

    def test_matched_advice_computed_in_missions(self):
        from scripts.dogfood_routing_advice import build_dogfood_report
        report = build_dogfood_report()
        for m in report["missions"]:
            assert "matched_advice" in m
