"""Tests for mission_status_report script logic."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
from mission_status_report import compute_report


def _run(overrides: dict) -> dict:
    base = {
        "mission_id": "x",
        "success": True,
        "status": "success",
        "duration_s": 10.0,
        "provider_used": "openrouter",
        "model_used": "gpt-oss-120b:free",
        "error_category": None,
    }
    return {**base, **overrides}


def test_empty_runs():
    r = compute_report([])
    assert r["total"] == 0


def test_counts_success_and_failed():
    runs = [_run({"success": True}), _run({"success": False, "status": "failed", "error_category": "timeout"})]
    r = compute_report(runs)
    assert r["total"] == 2
    assert r["success"] == 1
    assert r["failed"] == 1


def test_avg_duration():
    runs = [_run({"duration_s": 10.0}), _run({"duration_s": 20.0})]
    r = compute_report(runs)
    assert r["avg_duration_s"] == 15.0


def test_artifact_invalid_counted():
    runs = [_run({"success": False, "status": "failed", "error_category": "artifact_invalid"})]
    r = compute_report(runs)
    assert r["artifact_invalid"] == 1


def test_provider_unavailable_counted():
    runs = [_run({"success": False, "status": "failed", "error_category": "provider_unavailable"})]
    r = compute_report(runs)
    assert r["provider_unavailable"] == 1


def test_providers_counted():
    runs = [_run({}), _run({"provider_used": "ollama"})]
    r = compute_report(runs)
    assert r["providers_used"]["openrouter"] == 1
    assert r["providers_used"]["ollama"] == 1


def test_no_prompt_or_secret_in_report():
    runs = [_run({})]
    r = compute_report(runs)
    report_str = str(r)
    assert "sk-or-v1" not in report_str
    assert "prompt" not in report_str
