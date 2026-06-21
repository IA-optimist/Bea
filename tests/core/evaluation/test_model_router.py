"""Tests for core.evaluation.model_router."""
from __future__ import annotations

import pytest

from core.evaluation.model_router import ModelClass, ModelRouter
from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def router(tmp_path):
    store = OperationalMemoryStore(db_path=str(tmp_path / "router.db"))
    return ModelRouter(store=store)


def test_summary_uses_small_fast(router):
    decision = router.choose("summary of errors")
    assert decision.model_class == ModelClass.SMALL_FAST


def test_simple_patch_uses_medium_tool_use(router):
    decision = router.choose("apply simple patch")
    assert decision.model_class == ModelClass.MEDIUM_TOOL_USE


def test_complex_bug_uses_strong_reasoning(router):
    decision = router.choose("debug complex race condition")
    assert decision.model_class == ModelClass.STRONG_REASONING


def test_protected_file_uses_strong_code_review(router):
    decision = router.choose(
        "refactor auth helper",
        protected_files=["core/auth.py"],
    )
    assert decision.model_class == ModelClass.STRONG_CODE_REVIEW


def test_no_budget_uses_local_fallback(router):
    decision = router.choose("refactor auth", budget_cloud=False)
    assert decision.model_class == ModelClass.LOCAL_FALLBACK


def test_history_favors_successful_class(router, tmp_path):
    # Seed two successful MEDIUM_TOOL_USE results for "patch" task type
    for _ in range(2):
        router.store.add(MemoryItem(
            type=MemoryItemType.MODEL_RESULT,
            title="Medium success",
            content="Medium model succeeded on patch.",
            status=MemoryItemStatus.ACTIVE,
            tags=["patch"],
            metadata={
                "model": "medium",
                "model_class": "MEDIUM_TOOL_USE",
                "task_type": "patch",
                "success": True,
                "duration_ms": 500,
            },
        ))
    decision = router.choose("patch")
    assert decision.model_class == ModelClass.MEDIUM_TOOL_USE


def test_history_deprioritizes_failing_class(router, tmp_path):
    # Seed three failing SMALL_FAST results, then active default rule would be SMALL_FAST for summary.
    for _ in range(3):
        router.store.add(MemoryItem(
            type=MemoryItemType.MODEL_RESULT,
            title="Small failure",
            content="Small model failed on summary.",
            status=MemoryItemStatus.ACTIVE,
            tags=["summary"],
            metadata={
                "model": "small",
                "model_class": "SMALL_FAST",
                "task_type": "summary",
                "success": False,
                "duration_ms": 100,
            },
        ))
    decision = router.choose("summary of logs")
    # Either reverts to MEDIUM_TOOL_USE default or keeps SMALL_FAST if no alternative history
    assert decision.model_class != ModelClass.SMALL_FAST
