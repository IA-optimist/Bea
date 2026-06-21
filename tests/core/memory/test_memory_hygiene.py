"""Tests for memory ranking hygiene (active>obsolete, low_importance, private_joke)."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def store(tmp_path):
    return OperationalMemoryStore(db_path=str(tmp_path / "hygiene.db"))


def test_active_beats_obsolete(store):
    active = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Active fact",
        content="Current approach.",
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


def test_related_files_boost_ranking(store):
    target = "core/module.py"
    with_file = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Fact with file",
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


def test_low_importance_lowers_ranking(store):
    important = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Important fact",
        content="Critical architectural rule.",
        confidence=0.9,
        tags=["rule"],
    )
    low = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Low priority note",
        content="Minor note about style.",
        confidence=0.9,
        tags=["rule"],
    )
    low.metadata["importance"] = "low"
    store.add(important)
    store.add(low)
    ranked = store.ranked_search(query="rule", tags=["rule"], limit=2)
    assert ranked[0][0].id == important.id
    # Low importance score should be strictly below the important one
    assert ranked[0][1] > ranked[1][1] if len(ranked) > 1 else True


def test_private_joke_excluded_from_technical_mission(store):
    private = MemoryItem(
        type=MemoryItemType.FUN_FACT,
        title="Fun fact romantique sur Max",
        content="Max aime que Béa retienne qu'il est l'amour de la vie de sa petite amie.",
        tags=["private_joke", "humour", "romance"],
        source="seed:fun_fact",
        confidence=0.9,
        metadata={"importance": "low", "privacy": "personal", "not_for_decision": True},
    )
    fact = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="API v3 auth",
        content="API v3 uses bearer tokens.",
        tags=["api", "v3"],
        confidence=0.9,
    )
    store.add(private)
    store.add(fact)
    results = store.ranked_search(query="analyse API v3", type=MemoryItemType.REPO_FACT, limit=5)
    assert not any(r.title == private.title for r, _ in results)


def test_private_joke_included_for_light_mission(store):
    private = MemoryItem(
        type=MemoryItemType.FUN_FACT,
        title="Fun fact romantique sur Max",
        content="Max aime que Béa retienne qu'il est l'amour de la vie de sa petite amie.",
        tags=["private_joke", "humour", "romance"],
        source="seed:fun_fact",
        confidence=0.9,
        metadata={"importance": "low", "privacy": "personal", "not_for_decision": True},
    )
    store.add(private)
    results = store.ranked_search(query="fun fact Max", limit=5)
    assert any(r.title == private.title for r, _ in results)


def test_private_joke_not_returned_without_light_query(store):
    private = MemoryItem(
        type=MemoryItemType.FUN_FACT,
        title="Fun fact",
        content="Private joke.",
        tags=["private_joke"],
        metadata={"not_for_decision": True},
    )
    store.add(private)
    results = store.ranked_search(query="architecture decision", limit=5)
    assert not any(r.title == private.title for r, _ in results)


def test_no_source_penalized(store):
    sourced = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Sourced fact",
        content="Has a source.",
        source="audit",
        confidence=0.8,
        tags=["fact"],
    )
    no_source = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Orphan fact",
        content="Has no source.",
        source="",
        confidence=0.8,
        tags=["fact"],
    )
    store.add(sourced)
    store.add(no_source)
    results = store.ranked_search(query="fact", tags=["fact"], limit=2)
    assert results[0][0].id == sourced.id
