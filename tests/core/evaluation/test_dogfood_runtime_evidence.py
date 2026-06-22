"""Tests for scripts/dogfood_runtime_evidence.py."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import dogfood_runtime_evidence as dre


def test_fixture_pack_has_ten_missions_and_runtime_flags(tmp_path):
    output = tmp_path / "dogfood_runtime_evidence.json"
    report = dre.build_dogfood_runtime_evidence(mode="fixture", output_path=output)

    assert report["mode"] == "fixture"
    assert report["runtime_enforced"] is False
    assert report["summary"]["runtime_enforced"] is False
    assert len(report["missions"]) == 10
    assert report["summary"]["total"] == 10
    assert report["summary"]["matched_advice_count"] == report["summary"]["matched_advice"]

    for mission in report["missions"]:
        assert mission["runtime_enforced"] is False
        assert mission["mode"] == "fixture"
        assert mission["report_path"]
        assert mission["provider_status"] in {"fixture", "ready", "fallback", "provider_unavailable"}
        assert mission["goal"]
        assert mission["provider_used"] is not None
        assert mission["model_used"] is not None
        assert Path(mission["report_path"]).exists()


def test_fixture_pack_writes_per_mission_reports(tmp_path):
    output = tmp_path / "nested" / "dogfood_runtime_evidence.json"
    dre.build_dogfood_runtime_evidence(mode="fixture", output_path=output)
    report_dir = output.parent / f"{output.stem}_reports"

    assert output.parent.exists()
    assert report_dir.exists()
    assert len(list(report_dir.glob("*.json"))) == 10

    sample = json.loads((report_dir / "forge-builder-sha256.json").read_text(encoding="utf-8"))
    assert sample["mission_id"] == "forge-builder-sha256"
    assert sample["passed"] in {True, False}
    assert sample["runtime_enforced"] is False
    assert sample["report_path"].endswith("forge-builder-sha256.json")
    assert sample["artifacts"]
    assert sample["tests_run"]


def test_code_mission_without_artifact_is_not_passed():
    report = dre.build_dogfood_runtime_evidence(mode="fixture")
    mission = next(m for m in report["missions"] if m["mission_id"] == "forge-builder-mini-refactor")
    assert mission["passed"] is False
    assert mission["success"] is False
    assert mission["artifacts"] == []
    assert mission["provider_status"] == "fixture"


def test_json_mission_with_markdown_wrapper_is_not_passed():
    report = dre.build_dogfood_runtime_evidence(mode="fixture")
    mission = next(m for m in report["missions"] if m["mission_id"] == "shadow-json-release")
    assert mission["passed"] is False
    assert mission["score"] < 1.0
    assert mission["provider_status"] == "fixture"


def test_no_api_key_leaks_from_pack():
    report = dre.build_dogfood_runtime_evidence(mode="fixture")
    payload = json.dumps(report, ensure_ascii=False)
    assert "sk-or-v1" not in payload
    assert "Bearer " not in payload


def test_real_mode_provider_unavailable_is_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(dre, "_run_live_benchmark", lambda output_dir: (None, "provider_unavailable"))
    report = dre.build_dogfood_runtime_evidence(mode="real", output_path=tmp_path / "real.json")

    assert report["mode"] == "real"
    assert report["source"] == "provider_unavailable"
    assert report["summary"]["skipped"] == 10
    assert report["summary"]["failed"] == 0
    assert report["summary"]["passed"] == 0
    assert all(m["provider_status"] == "provider_unavailable" for m in report["missions"])
    assert all(m["skipped"] is True for m in report["missions"])
