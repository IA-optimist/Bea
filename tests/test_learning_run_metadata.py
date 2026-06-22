"""Tests for provider/model metadata propagation through the learning pipeline.

Two complementary mechanisms are tested:

  1. session_meta_bus (ContextVar) — tracks actual LLM calls.
     Works because ContextVars are async-task-scoped; no session_id needed.
     Used by: llm_factory → bea_executor → session.metadata

  2. _session_provider_meta (dict) — original approach from preserve-provider PR.
     Requires agents to pass session_id to safe_invoke(); currently never happens
     at runtime (agents call safe_invoke without session_id).  Kept for explicit
     use cases and tested in isolation.

  3. build_learning_run_payload — writer that reads session.metadata.
     This is what lands in learning_runs.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.executor.pipeline_auto import build_learning_run_payload
from core.executor.session_meta_bus import (
    LLMCall,
    build_session_metadata_patch,
    get_calls,
    get_initial_meta,
    get_primary_model,
    get_primary_provider,
    get_providers_used,
    is_fallback_used,
    record_llm_used,
    reset,
    set_initial_meta,
)
from core.learning.learning_engine import LearningEngine
from core.llm_factory import (
    _record_session_provider,
    get_and_clear_session_provider_meta,
    _session_provider_meta,
    _session_provider_lock,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── build_learning_run_payload (writer) ───────────────────────────────────────

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


def test_build_learning_run_payload_includes_fallback_used():
    session = _make_session(
        metadata={
            "mission_id": "m-fb",
            "provider_used": "ollama",
            "model_used": "gemma4:12b",
            "fallback_used": True,
            "provider_status": "fallback",
        },
    )
    payload = build_learning_run_payload(
        session,
        "code",
        {"label": "SUCCESS", "ok": 1, "total": 1, "rate": 1.0},
        session_ok=True,
    )
    assert payload["fallback_used"] is True
    assert payload["provider_status"] == "fallback"
    assert payload["provider_used"] == "ollama"


def test_build_learning_run_payload_no_key_invented():
    """provider/model must stay None when not set — never invent a value."""
    session = _make_session(metadata={})
    payload = build_learning_run_payload(
        session,
        "auto",
        {"label": "SUCCESS", "ok": 0, "total": 0, "rate": 0.0},
        session_ok=True,
    )
    assert payload["provider_used"] is None
    assert payload["model_used"] is None
    assert payload.get("fallback_used") is None  # not invented


# ── session_meta_bus — ContextVar tracking ────────────────────────────────────

@pytest.fixture(autouse=True)
def _bus_reset():
    """Ensure a clean bus state for every test."""
    reset()
    yield
    reset()


class TestSessionMetaBus:

    def test_record_primary_call(self):
        record_llm_used("openrouter", "openai/gpt-oss-20b:free")
        assert get_primary_provider() == "openrouter"
        assert get_primary_model() == "openai/gpt-oss-20b:free"
        assert is_fallback_used() is False

    def test_record_fallback_call(self):
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        assert get_primary_provider() == "ollama"
        assert is_fallback_used() is True

    def test_primary_wins_over_fallback(self):
        record_llm_used("openrouter", "gpt-oss-20b:free")
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        assert get_primary_provider() == "openrouter"
        assert is_fallback_used() is True  # fallback was also used

    def test_fallback_only_when_no_primary(self):
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        assert get_primary_provider() == "ollama"
        assert get_primary_model() == "gemma4:12b"

    def test_providers_used_deduped(self):
        record_llm_used("openrouter", "model-a")
        record_llm_used("openrouter", "model-b")
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        assert get_providers_used() == ["openrouter", "ollama"]

    def test_get_calls_returns_all(self):
        record_llm_used("openrouter", "m1")
        record_llm_used("ollama", "m2", fallback=True)
        calls = get_calls()
        assert len(calls) == 2
        assert calls[0] == LLMCall("openrouter", "m1", False)
        assert calls[1] == LLMCall("ollama", "m2", True)

    def test_empty_state_returns_none(self):
        assert get_primary_provider() is None
        assert get_primary_model() is None
        assert is_fallback_used() is False
        assert get_providers_used() == []

    def test_reset_clears_state(self):
        record_llm_used("openrouter", "model-x")
        reset()
        assert get_primary_provider() is None


class TestInitialMeta:

    def test_set_and_get(self):
        set_initial_meta({
            "provider_used": "openrouter",
            "mission_type": "code",
            "fallback_used": False,
        })
        meta = get_initial_meta()
        assert meta["provider_used"] == "openrouter"
        assert meta["mission_type"] == "code"
        assert meta["fallback_used"] is False

    def test_none_values_excluded(self):
        set_initial_meta({"provider_used": "openrouter", "model_used": None})
        meta = get_initial_meta()
        assert "model_used" not in meta
        assert meta["provider_used"] == "openrouter"

    def test_initial_meta_used_when_no_calls(self):
        set_initial_meta({"provider_used": "openrouter", "mission_type": "code"})
        patch = build_session_metadata_patch({})
        assert patch["provider_used"] == "openrouter"
        assert patch["mission_type"] == "code"

    def test_actual_calls_win_over_planned(self):
        set_initial_meta({"provider_used": "openrouter"})
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        patch = build_session_metadata_patch({})
        # actual call used ollama
        assert patch["provider_used"] == "ollama"
        assert patch["fallback_used"] is True


class TestBuildSessionMetadataPatch:

    def test_patch_populated_from_actual_calls(self):
        record_llm_used("openrouter", "openai/gpt-oss-120b:free")
        patch = build_session_metadata_patch({})
        assert patch["provider_used"] == "openrouter"
        assert patch["model_used"] == "openai/gpt-oss-120b:free"
        assert patch["fallback_used"] is False
        assert patch["provider_status"] == "primary"

    def test_patch_fallback_flag_when_ollama(self):
        record_llm_used("ollama", "gemma4:12b", fallback=True)
        patch = build_session_metadata_patch({})
        assert patch["fallback_used"] is True
        assert patch["provider_status"] == "fallback"

    def test_patch_does_not_overwrite_existing(self):
        record_llm_used("ollama", "gemma4:12b")
        existing = {"provider_used": "openrouter", "model_used": "gpt-4"}
        patch = build_session_metadata_patch(existing)
        assert "provider_used" not in patch  # existing preserved
        assert "model_used" not in patch

    def test_patch_empty_when_no_data(self):
        patch = build_session_metadata_patch({})
        # No provider_used, no model_used invented
        assert patch.get("provider_used") is None or "provider_used" not in patch
        assert patch.get("model_used") is None or "model_used" not in patch

    def test_no_api_key_in_patch(self):
        set_initial_meta({"provider_used": "openrouter"})
        record_llm_used("openrouter", "gpt-oss-20b:free")
        patch = build_session_metadata_patch({})
        for key, value in patch.items():
            if isinstance(value, str):
                assert "sk-" not in value, f"Possible API key in {key}"


# ── session_metadata flows into build_learning_run_payload ───────────────────

def test_end_to_end_bus_to_learning_run():
    """Simulate the full path: bus records call → bea_executor patches metadata
    → build_learning_run_payload writes to learning_runs.json."""
    record_llm_used("openrouter", "openai/gpt-oss-20b:free")
    set_initial_meta({"mission_type": "code", "provider_used": "openrouter"})

    # Simulate bea_executor injecting into session.metadata
    base_meta = {"mission_id": "m-e2e"}
    patch = build_session_metadata_patch(base_meta)
    base_meta.update(patch)

    session = _make_session(metadata=base_meta, outputs={
        "forge-builder": SimpleNamespace(success=True),
        "scout-research": SimpleNamespace(success=False),
    })
    payload = build_learning_run_payload(
        session,
        "code",
        {"label": "PARTIAL", "ok": 1, "total": 2, "rate": 0.5},
        session_ok=False,
    )

    assert payload["provider_used"] == "openrouter"
    assert payload["model_used"] == "openai/gpt-oss-20b:free"
    assert payload["mission_type"] == "code"
    assert payload["fallback_used"] is False
    assert payload["agents_used"] == ["forge-builder", "scout-research"]


def test_end_to_end_ollama_fallback_to_learning_run():
    """Ollama fallback → fallback_used=True in learning_runs.json."""
    record_llm_used("ollama", "gemma4:12b", fallback=True)
    set_initial_meta({"provider_used": "openrouter", "mission_type": "research"})

    base_meta = {}
    patch = build_session_metadata_patch(base_meta)
    base_meta.update(patch)

    session = _make_session(metadata=base_meta)
    payload = build_learning_run_payload(
        session,
        "research",
        {"label": "SUCCESS", "ok": 1, "total": 1, "rate": 1.0},
        session_ok=True,
    )

    assert payload["provider_used"] == "ollama"
    assert payload["model_used"] == "gemma4:12b"
    assert payload["fallback_used"] is True
    assert payload["provider_status"] == "fallback"


def test_no_provider_invented_when_no_data():
    """When no LLM call happened and no routing info exists, keep null."""
    # Empty bus state
    base_meta = {}
    patch = build_session_metadata_patch(base_meta)
    base_meta.update(patch)

    session = _make_session(metadata=base_meta)
    payload = build_learning_run_payload(
        session,
        "auto",
        {"label": "FAILURE", "ok": 0, "total": 1, "rate": 0.0},
        session_ok=False,
    )
    assert payload["provider_used"] is None
    assert payload["model_used"] is None


# ── LearningEngine persistence ────────────────────────────────────────────────

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
            "fallback_used": True,
            "success": True,
            "duration_s": 3.2,
        }
    )

    data = json.loads((workspace / "learning_runs.json").read_text(encoding="utf-8"))
    assert data[0]["run_id"] == run_id
    assert data[0]["provider_used"] == "ollama"
    assert data[0]["model_used"] == "gemma4:12b"
    assert data[0]["fallback_used"] is True
    assert engine.get_recent_runs(1)[0]["mission_id"] == "mission-789"


# ── _session_provider_meta (dict tracker, prev PR) ───────────────────────────

def _clean_tracker(*sids: str) -> None:
    with _session_provider_lock:
        for sid in sids:
            _session_provider_meta.pop(sid, None)


class TestSessionProviderTracker:
    """Unit tests for the dict-based tracker added by preserve-provider PR.

    Note: this tracker is only fed when agents explicitly pass session_id to
    safe_invoke(); that does not happen in the current runtime.  Tests verify
    the tracker's own logic in isolation.
    """

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
