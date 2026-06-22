from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.executor.pipeline_auto import build_learning_run_payload
from core.learning.learning_engine import LearningEngine
from core.llm_factory import (
    _record_session_provider,
    get_and_clear_session_provider_meta,
    _session_provider_meta,
    _session_provider_lock,
)


@dataclass
class _Settings:
    workspace_dir: str


def _make_session(**kwargs):
    base = dict(
        session_id="session-123",
        mission_summary="Build a SHA256 helper.",
        created_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
        outputs={
            "forge-builder": SimpleNamespace(success=True),
        },
        improve_pending=[],
        auto_count=1,
        actions_executed=[{"id": "action-1"}],
        metadata={
            "mission_id": "mission-123",
            "mission_type": "coding_task",
            "provider_used": "openrouter",
            "model_used": "openai/gpt-oss-20b:free",
            "duration_s": 12.5,
            "error_category": None,
            "report_path": "workspace/report.json",
        },
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_build_learning_run_payload_preserves_provider_and_model():
    session = _make_session()
    payload = build_learning_run_payload(
        session,
        "code",
        {"label": "SUCCESS", "ok": 1, "total": 1, "rate": 1.0},
        session_ok=True,
    )

    assert payload["mission_id"] == "mission-123"
    assert payload["mission_type"] == "coding_task"
    assert payload["provider_used"] == "openrouter"
    assert payload["model_used"] == "openai/gpt-oss-20b:free"
    assert payload["agent_used"] == "forge-builder"
    assert payload["agents_used"] == ["forge-builder"]
    assert payload["success"] is True
    assert payload["duration_s"] == 12.5
    assert payload["report_path"] == "workspace/report.json"


def test_build_learning_run_payload_accepts_unknown_provider_and_model():
    session = _make_session(
        metadata={
            "mission_id": "mission-456",
            "mission_type": "coding_task",
        },
    )
    payload = build_learning_run_payload(
        session,
        "code",
        {"label": "FAILURE", "ok": 0, "total": 1, "rate": 0.0},
        session_ok=False,
    )

    assert payload["provider_used"] is None
    assert payload["model_used"] is None
    assert payload["success"] is False
    assert payload["error_category"] is None


def test_learning_engine_persists_existing_minimal_format(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    legacy_path = workspace / "learning_runs.json"
    legacy_path.write_text(
        json.dumps([
            {
                "run_id": "run_legacy",
                "mode": "improve",
                "status": "SUCCESS",
                "success_rate": 1.0,
            }
        ]),
        encoding="utf-8",
    )

    engine = LearningEngine(_Settings(workspace_dir=str(workspace)))
    recent = engine.get_recent_runs(1)

    assert recent[0]["run_id"] == "run_legacy"
    assert recent[0]["mode"] == "improve"
    assert "provider_used" not in recent[0]
    assert "model_used" not in recent[0]


def test_learning_engine_round_trips_provider_model_fields(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine = LearningEngine(_Settings(workspace_dir=str(workspace)))
    engine.clear()

    run_id = engine.record_run(
        {
            "mode": "code",
            "mission_id": "mission-789",
            "mission_type": "coding_task",
            "provider_used": "ollama",
            "model_used": "gemma4:12b",
            "success": True,
            "duration_s": 3.2,
        }
    )

    data = json.loads((workspace / "learning_runs.json").read_text(encoding="utf-8"))
    assert data[0]["run_id"] == run_id
    assert data[0]["provider_used"] == "ollama"
    assert data[0]["model_used"] == "gemma4:12b"
    assert engine.get_recent_runs(1)[0]["mission_id"] == "mission-789"


# ── Tracker unit tests ────────────────────────────────────────────────────────

def _clean_tracker(*sids: str) -> None:
    with _session_provider_lock:
        for sid in sids:
            _session_provider_meta.pop(sid, None)


class TestSessionProviderTracker:

    def setup_method(self):
        _clean_tracker("t-a", "t-b", "t-c", "t-d")

    def test_primary_recorded(self):
        _record_session_provider("t-a", "openrouter", "gpt-oss-20b:free", fallback=False)
        meta = get_and_clear_session_provider_meta("t-a")
        assert meta["provider_used"] == "openrouter"
        assert meta["model_used"] == "gpt-oss-20b:free"
        assert meta["fallback_used"] is False

    def test_first_write_wins(self):
        _record_session_provider("t-b", "openrouter", "model-A", fallback=False)
        _record_session_provider("t-b", "ollama", "gemma4:12b", fallback=False)
        assert get_and_clear_session_provider_meta("t-b")["provider_used"] == "openrouter"

    def test_fallback_recorded_when_no_primary(self):
        _record_session_provider("t-c", "ollama", "gemma4:12b", fallback=True)
        meta = get_and_clear_session_provider_meta("t-c")
        assert meta["provider_used"] == "ollama"
        assert meta["fallback_used"] is True

    def test_clear_after_read(self):
        _record_session_provider("t-d", "openrouter", "model-X", fallback=False)
        get_and_clear_session_provider_meta("t-d")
        assert get_and_clear_session_provider_meta("t-d") == {}

    def test_missing_session_empty(self):
        assert get_and_clear_session_provider_meta("never-existed-xyz") == {}

    def test_empty_session_id_ignored(self):
        _record_session_provider("", "openrouter", "model-X", fallback=False)
        _clean_tracker("")
