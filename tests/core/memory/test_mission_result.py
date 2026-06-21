"""Tests for core.memory.mission_result."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItemStatus, MemoryItemType
from core.memory.mission_result import MissionResult, MissionResultRecorder
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def recorder(tmp_path):
    store = OperationalMemoryStore(db_path=str(tmp_path / "result.db"))
    return MissionResultRecorder(store=store)


def test_record_success_creates_eval_model_result_skill_test_map(recorder):
    result = MissionResult(
        mission_id="m1",
        run_id="r1",
        task_type="refactor",
        files_changed=["core/foo.py"],
        tests_run=["tests/core/foo_test.py"],
        success=True,
        model_used="claude-3-5-sonnet",
        model_class="MEDIUM_TOOL_USE",
        duration_ms=1000,
        created_skill="Refactor legacy function",
    )
    created = recorder.record(result)
    assert "eval_result" in created
    assert "model_result" in created
    assert "skill" in created
    assert "test_map" in created

    eval_item = recorder.store.get(created["eval_result"])
    assert eval_item.type == MemoryItemType.EVAL_RESULT
    assert eval_item.metadata["success"] is True


def test_record_failure_creates_bug_memory(recorder):
    result = MissionResult(
        mission_id="m2",
        run_id="r2",
        task_type="bugfix",
        files_changed=["core/bar.py"],
        tests_run=["tests/core/bar_test.py"],
        success=False,
        failure_reason="IndexError on empty list",
        model_used="gpt-4",
        model_class="STRONG_REASONING",
        duration_ms=2000,
    )
    created = recorder.record(result)
    assert "bug_memory" in created
    bug = recorder.store.get(created["bug_memory"])
    assert bug.type == MemoryItemType.BUG_MEMORY
    assert bug.status == MemoryItemStatus.ACTIVE
    assert "IndexError" in bug.content
