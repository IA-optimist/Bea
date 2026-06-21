from __future__ import annotations

import json

import pytest

from scripts import smoke_e2e_cycle


def _valid_report() -> dict[str, object]:
    return {
        "mission_id": "smoke-contract-success",
        "goal": "Prove the coding-agent report contract.",
        "mission_type": "coding_agent",
        "success": True,
        "agents_used": ["codex"],
        "tools_used": ["pytest"],
        "plan_steps": ["write test", "run smoke"],
        "complexity": "low",
        "error_category": "",
        "duration_s": 1.2,
        "report_path": "report.json",
    }


def test_report_contract_accepts_valid_coding_agent_report(tmp_path):
    report_path = tmp_path / "report.json"
    report = _valid_report()
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    loaded = smoke_e2e_cycle.validate_report_contract(report_path)

    assert loaded["mission_id"] == "smoke-contract-success"
    assert loaded["mission_type"] == "coding_agent"


def test_report_contract_rejects_missing_required_fields(tmp_path):
    report_path = tmp_path / "report.json"
    report = _valid_report()
    del report["goal"]
    del report["tools_used"]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(smoke_e2e_cycle.SmokeE2EError) as exc:
        smoke_e2e_cycle.validate_report_contract(report_path)

    message = str(exc.value)
    assert "missing required report field(s)" in message
    assert "goal" in message
    assert "tools_used" in message
