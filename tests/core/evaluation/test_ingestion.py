"""Tests for core.evaluation.ingestion and the CLI script."""
from __future__ import annotations

from pathlib import Path

import json

from core.evaluation.ingestion import ingest


def test_ingest_directory(tmp_path):
    report = {
        "mission_id": "ingest-1",
        "title": "Ingested mission",
        "status": "SUCCESS",
        "task_type": "feature",
        "files_changed": ["core/foo.py"],
        "tests_run": ["tests/test_foo.py"],
        "success": True,
        "model_used": "claude",
        "model_class": "MEDIUM_TOOL_USE",
        "lessons_learned": "Ingestion works.",
    }
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report))
    result = ingest(tmp_path)
    assert result["reports_read"] == 1
    assert result["memories_created"] > 0
    assert result["memories_updated"] == 0
    assert len(result["errors"]) == 0


def test_ingest_file(tmp_path):
    report_file = tmp_path / "report.json"
    report_file.write_text('{\n  "mission_id": "file-1",\n  "status": "FAILURE",\n  "failure_reason": "Oops"\n}\n')
    result = ingest(report_file)
    assert result["reports_read"] == 1
    assert result["memories_created"] >= 1


def test_ingest_fixtures():
    root = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures" / "mission_reports"
    result = ingest(root)
    assert result["reports_read"] == 4
    assert result["memories_created"] > 0
    assert result["details"]
