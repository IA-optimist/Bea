"""Tests for core.evaluation.mission_report_parser."""
from __future__ import annotations

import json

import pytest

from core.evaluation.mission_report_parser import MissionReportParser


@pytest.fixture
def parser():
    return MissionReportParser()


def test_parse_success_json(parser):
    raw = json.dumps({
        "mission_id": "m1",
        "title": "Add feature",
        "status": "SUCCESS",
        "task_type": "feature",
        "files_changed": ["core/foo.py"],
        "tests_run": ["tests/test_foo.py"],
        "success": True,
        "model_used": "claude",
        "model_class": "MEDIUM_TOOL_USE",
        "duration_ms": 1000,
        "cost_estimate": 0.01,
        "lessons_learned": "Lessons",
        "risks_detected": ["risk"],
    })
    inp = parser.parse(raw)
    assert inp.mission_id == "m1"
    assert inp.title == "Add feature"
    assert inp.success is True
    assert inp.task_type == "feature"
    assert inp.files_changed == ["core/foo.py"]
    assert inp.tests_run == ["tests/test_foo.py"]
    assert inp.model_used == "claude"
    assert inp.model_class == "MEDIUM_TOOL_USE"
    assert inp.duration_ms == 1000
    assert inp.cost_estimate == 0.01
    assert inp.risks_detected == ["risk"]


def test_parse_camel_case_keys(parser):
    raw = json.dumps({
        "missionId": "m2",
        "taskType": "bugfix",
        "filesChanged": "core/foo.py, core/bar.py",
        "durationMs": 500,
        "costEstimate": 0.005,
    })
    inp = parser.parse(raw)
    assert inp.mission_id == "m2"
    assert inp.task_type == "bugfix"
    assert inp.files_changed == ["core/foo.py", "core/bar.py"]
    assert inp.duration_ms == 500


def test_parse_missing_fields_does_not_crash(parser):
    raw = json.dumps({"mission_id": "m3"})
    inp = parser.parse(raw)
    assert inp.mission_id == "m3"
    assert inp.title == ""
    assert inp.success is False
    assert any("Missing task_type" in w for w in inp.warnings)


def test_parse_status_derives_success(parser):
    inp = parser.parse(json.dumps({"status": "completed"}))
    assert inp.success is True
    inp = parser.parse(json.dumps({"status": "FAILURE"}))
    assert inp.success is False


def test_parse_markdown_minimal(parser):
    md = """
# Mission Report

Title: Update docs
Status: SUCCESS
Task type: docs
Model: claude-3-5-sonnet
Model class: SMALL_FAST
Duration: 1200ms
Files changed:
- core/docs.md
Tests run:
- tests/test_docs.py
Lessons learned: Keep docs in sync with code.
"""
    inp = parser.parse(md)
    assert inp.title == "Update docs"
    assert inp.success is True
    assert inp.task_type == "docs"
    assert inp.model_used == "claude-3-5-sonnet"
    assert inp.model_class == "SMALL_FAST"
    assert inp.duration_ms == 1200
    assert "core/docs.md" in inp.files_changed
    assert "tests/test_docs.py" in inp.tests_run


def test_parse_file(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"mission_id": "file-mission", "title": "File mission"}))
    inp = MissionReportParser().parse_file(path)
    assert inp.mission_id == "file-mission"
