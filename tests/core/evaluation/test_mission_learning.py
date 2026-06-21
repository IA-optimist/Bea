"""Tests for core.evaluation.mission_learning."""
from __future__ import annotations

import json

import pytest

from core.evaluation.mission_learning import MissionLearner, learn_from_mission_report
from core.evaluation.mission_report_parser import MissionLearningInput
from core.memory.memory_item import MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def learner(tmp_path):
    store = OperationalMemoryStore(db_path=str(tmp_path / "learning.db"))
    return MissionLearner(store=store)


def test_learn_from_success_creates_eval_model_result_skill_test_map(learner):
    inp = MissionLearningInput(
        mission_id="m1",
        title="Add feature",
        status="SUCCESS",
        task_type="feature",
        files_changed=["core/foo.py"],
        tests_run=["tests/test_foo.py"],
        success=True,
        model_used="claude",
        model_class="MEDIUM_TOOL_USE",
        duration_ms=1000,
        cost_estimate=0.01,
        lessons_learned="Add tests first.",
    )
    result = learner.learn(inp)
    assert len(result.created_memory_ids) >= 4
    assert len(result.errors) == 0

    types = set()
    for mid in result.created_memory_ids:
        item = learner.store.get(mid)
        types.add(item.type)
    assert MemoryItemType.EVAL_RESULT in types
    assert MemoryItemType.MODEL_RESULT in types
    assert MemoryItemType.SKILL in types
    assert MemoryItemType.TEST_MAP in types


def test_learn_from_failure_creates_bug_memory(learner):
    inp = MissionLearningInput(
        mission_id="m2",
        title="Fix auth",
        status="NEEDS_FIX",
        task_type="bugfix",
        files_changed=["core/auth.py"],
        tests_run=["tests/test_auth.py"],
        success=False,
        failure_reason="Token bypass regression.",
        model_used="gpt-4",
        model_class="STRONG_CODE_REVIEW",
    )
    result = learner.learn(inp)
    bug = None
    for mid in result.created_memory_ids:
        item = learner.store.get(mid)
        if item.type == MemoryItemType.BUG_MEMORY:
            bug = item
    assert bug is not None
    assert "Token bypass" in bug.content


def test_learn_from_protected_file_creates_risk(learner):
    inp = MissionLearningInput(
        mission_id="m3",
        title="Kernel patch",
        status="SUCCESS",
        task_type="security_patch",
        files_changed=["kernel/policy/gate.py"],
        tests_run=["tests/kernel/test_gate.py"],
        success=True,
        model_used="claude",
        model_class="STRONG_CODE_REVIEW",
        risks_detected=["Policy gate changed."],
    )
    result = learner.learn(inp)
    risks = [learner.store.get(mid) for mid in result.created_memory_ids if learner.store.get(mid).type == MemoryItemType.RISK]
    assert len(risks) >= 1
    assert any(r.status == MemoryItemStatus.DANGEROUS for r in risks)


def test_deduplication_updates_existing(learner):
    inp = MissionLearningInput(
        mission_id="m4",
        title="Same bug",
        status="FAILURE",
        task_type="bugfix",
        files_changed=["core/bar.py"],
        success=False,
        failure_reason="Same failure.",
    )
    r1 = learner.learn(inp)
    bug_id_1 = [m for m in r1.created_memory_ids if learner.store.get(m).type == MemoryItemType.BUG_MEMORY][0]

    r2 = learner.learn(inp)
    bug_id_2 = [m for m in r2.created_memory_ids if learner.store.get(m).type == MemoryItemType.BUG_MEMORY][0]

    assert bug_id_1 == bug_id_2
    bug = learner.store.get(bug_id_1)
    assert bug.metadata.get("occurrence_count", 1) >= 2
    assert bug.confidence > 0.75


def test_learn_from_mission_report_string(learner, tmp_path):
    report = {
        "mission_id": "m5",
        "title": "Docs update",
        "status": "SUCCESS",
        "task_type": "docs",
        "files_changed": ["docs/README.md"],
        "tests_run": [],
        "success": True,
        "model_used": "claude",
        "model_class": "SMALL_FAST",
        "lessons_learned": "Sync docs.",
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    result = learn_from_mission_report(path, store=learner.store)
    assert result.mission_id == "m5"
    assert len(result.created_memory_ids) >= 1
