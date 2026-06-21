"""Tests for memory ranking in OperationalMemoryStore."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def store(tmp_path):
    return OperationalMemoryStore(db_path=str(tmp_path / "ranking.db"))


def test_active_beats_obsolete(store):
    active = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Active fact",
        content="Current canonical approach.",
        status=MemoryItemStatus.ACTIVE,
        confidence=0.8,
        tags=["approach"],
    )
    obsolete = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Obsolete fact",
        content="Old approach.",
        status=MemoryItemStatus.OBSOLETE,
        confidence=0.95,
        tags=["approach"],
    )
    store.add(active)
    store.add(obsolete)
    ranked = store.ranked_search(query="approach", tags=["approach"], limit=2)
    assert ranked[0][0].id == active.id


def test_related_file_boosts_score(store):
    target = "core/module.py"
    with_file = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title=" Fact with file",
        content="Relevant to target module.",
        related_files=[target],
        confidence=0.8,
        tags=["module"],
    )
    without_file = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Generic fact",
        content="Relevant to target module.",
        confidence=0.8,
        tags=["module"],
    )
    store.add(without_file)
    store.add(with_file)
    ranked = store.ranked_search(
        type=MemoryItemType.REPO_FACT,
        query="target module",
        related_files=[target],
        tags=["module"],
        limit=2,
    )
    assert ranked[0][0].id == with_file.id


def test_replaced_not_preferred(store):
    replaced = MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Replaced decision",
        content="Old rule.",
        status=MemoryItemStatus.REPLACED,
        confidence=0.9,
    )
    current = MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Current decision",
        content="New rule.",
        status=MemoryItemStatus.ACTIVE,
        confidence=0.9,
    )
    store.add(replaced)
    store.add(current)
    ranked = store.ranked_search(query="rule", limit=2)
    assert ranked[0][0].id == current.id


def test_unverified_fallback_only_when_no_active(store):
    unverified = MemoryItem(
        type=MemoryItemType.BUG_MEMORY,
        title="Unverified bug",
        content="Maybe a bug.",
        status=MemoryItemStatus.UNVERIFIED,
        confidence=0.5,
        tags=["bug"],
    )
    store.add(unverified)
    ranked = store.ranked_search(query="bug", tags=["bug"], limit=2)
    assert len(ranked) == 1
    assert ranked[0][0].status == MemoryItemStatus.UNVERIFIED

    active = MemoryItem(
        type=MemoryItemType.BUG_MEMORY,
        title="Known bug",
        content="Confirmed bug.",
        status=MemoryItemStatus.ACTIVE,
        confidence=0.9,
        tags=["bug"],
    )
    store.add(active)
    ranked = store.ranked_search(query="bug", tags=["bug"], limit=2)
    assert ranked[0][0].status == MemoryItemStatus.ACTIVE


def test_score_positive_for_active_high_confidence(store):
    item = MemoryItem(
        type=MemoryItemType.SKILL,
        title="Skill",
        content="Reusable procedure.",
        status=MemoryItemStatus.ACTIVE,
        confidence=0.95,
        source="test",
    )
    store.add(item)
    ranked = store.ranked_search(query="procedure", limit=1)
    assert ranked[0][1] > 0
