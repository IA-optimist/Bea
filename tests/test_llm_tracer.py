"""Tests pour core.observability.llm_tracer — SQLite réel."""
from __future__ import annotations

import pytest

from core.observability.llm_tracer import LLMTracer


def test_record_and_stats():
    tr = LLMTracer(":memory:")
    tr.record("bea-v3.1", prompt_tokens=100, completion_tokens=50, cost_usd=0.001, mission_id="m1")
    tr.record("bea-v3.1", prompt_tokens=10, completion_tokens=5, cost_usd=0.0002, ok=False, error="boom", mission_id="m1")
    tr.record("codex", prompt_tokens=20, completion_tokens=10, cost_usd=0.0005, mission_id="m2")
    s = tr.stats()
    assert s["calls"] == 3
    assert s["error_rate"] == round(1 / 3, 4)
    assert "bea-v3.1" in s["by_model"] and s["by_model"]["bea-v3.1"]["calls"] == 2
    assert s["total_tokens"] == 100 + 50 + 10 + 5 + 20 + 10
    tr.close()


def test_cost_by_mission():
    tr = LLMTracer(":memory:")
    tr.record("m", cost_usd=0.01, mission_id="mA")
    tr.record("m", cost_usd=0.02, mission_id="mA")
    tr.record("m", cost_usd=0.05, mission_id="mB")
    assert tr.cost_by_mission("mA") == 0.03
    assert tr.cost_by_mission("mB") == 0.05
    tr.close()


def test_span_records_success_and_latency():
    tr = LLMTracer(":memory:")
    with tr.span(model="bea-v3.1", mission_id="m1") as s:
        s.set(prompt_tokens=5, completion_tokens=7, cost_usd=0.0003)
    assert tr.stats()["calls"] == 1
    assert tr.stats()["error_rate"] == 0.0
    tr.close()


def test_span_records_exception():
    tr = LLMTracer(":memory:")
    with pytest.raises(RuntimeError):
        with tr.span(model="bea-v3.1"):
            raise RuntimeError("llm failed")
    s = tr.stats()
    assert s["calls"] == 1 and s["error_rate"] == 1.0
    tr.close()
