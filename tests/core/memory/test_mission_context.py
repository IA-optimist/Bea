"""Tests for core.memory.mission_context."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.mission_context import MissionContextBuilder
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def builder(tmp_path):
    store = OperationalMemoryStore(db_path=str(tmp_path / "ctx.db"))
    return MissionContextBuilder(store=store)


def test_prepare_returns_decisions_and_risks(builder):
    decision = MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Auth route decision",
        content="All auth routes must use require_auth.",
        status=MemoryItemStatus.ACTIVE,
        confidence=0.9,
        related_files=["core/auth.py"],
        tags=["auth"],
    )
    risk = MemoryItem(
        type=MemoryItemType.RISK,
        title="Auth risk",
        content="Never auto-promote auth changes.",
        status=MemoryItemStatus.DANGEROUS,
        confidence=1.0,
        related_files=["core/auth.py"],
        tags=["auth", "security"],
    )
    builder.store.add(decision)
    builder.store.add(risk)

    ctx = builder.prepare(
        "Refactor auth",
        "Clean up auth module.",
        optional_files=["core/auth.py"],
        task_type="refactor",
    )
    assert any("auth" in d.title.lower() for d in ctx.relevant_decisions)
    assert any(d.status == MemoryItemStatus.DANGEROUS for d in ctx.relevant_risks)
    assert ctx.model_class_hint == "STRONG_CODE_REVIEW"
    assert "core/auth.py" in ctx.suggested_context_summary


def test_prepare_model_class_hint_for_simple_task(builder):
    ctx = builder.prepare(
        "Summarize failures",
        "Give a summary of last failures.",
        task_type="summary",
    )
    assert ctx.model_class_hint == "SMALL_FAST"


def test_prepare_obsolete_not_returned(builder):
    old = MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Old API",
        content="Use /v1.",
        status=MemoryItemStatus.OBSOLETE,
        related_files=["api/routes/v1.py"],
        tags=["api"],
    )
    builder.store.add(old)
    ctx = builder.prepare(
        "API change",
        "Update API.",
        optional_files=["api/routes/v1.py"],
        task_type="refactor",
    )
    # Either not returned or returned with low rank; here include_obsolete=False.
    assert not any(d.title == "Old API" for d in ctx.relevant_decisions)
