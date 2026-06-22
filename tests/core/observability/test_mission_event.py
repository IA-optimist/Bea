"""Tests for MissionEvent."""
from __future__ import annotations

import time

from core.observability.mission_event import MissionEvent


def test_to_log_dict_contains_mission_id():
    ev = MissionEvent(mission_id="test-123", mission_type="coding_agent")
    d = ev.to_log_dict()
    assert d["mission_id"] == "test-123"
    assert d["mission_type"] == "coding_agent"


def test_complete_sets_duration():
    ev = MissionEvent(mission_id="m1")
    time.sleep(0.01)
    ev.complete(status="success")
    assert ev.status == "success"
    assert ev.duration_ms is not None
    assert ev.duration_ms >= 0


def test_complete_sets_error_category():
    ev = MissionEvent(mission_id="m2")
    ev.complete(status="failed", error_category="artifact_invalid")
    assert ev.error_category == "artifact_invalid"


def test_to_log_dict_no_private_keys():
    ev = MissionEvent(mission_id="m3")
    d = ev.to_log_dict()
    assert "_start" not in d


def test_to_log_dict_provider_preserved():
    ev = MissionEvent(mission_id="m4", provider_used="openrouter", model_used="gpt-oss-120b:free")
    d = ev.to_log_dict()
    assert d["provider_used"] == "openrouter"
    assert d["model_used"] == "gpt-oss-120b:free"


def test_rate_limited_default_false():
    ev = MissionEvent(mission_id="m5")
    assert ev.rate_limited is False
    assert ev.fallback_used is False
