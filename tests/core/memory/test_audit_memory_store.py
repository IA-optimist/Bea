"""Tests for audit_memory_store.py."""
from __future__ import annotations

import pytest

from scripts.audit_memory_store import audit
from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def store(tmp_path):
    return OperationalMemoryStore(db_path=str(tmp_path / "audit.db"))


def test_audit_on_empty_store(store):
    report = audit(store)
    assert report.total == 0
    assert report.by_type == {}
    assert report.dry_run is True


def test_audit_counts_types_and_status(store):
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Fact",
        content="A fact.",
        source="test",
        confidence=0.9,
        tags=["api"],
    ))
    store.add(MemoryItem(
        type=MemoryItemType.BUG_MEMORY,
        title="Bug",
        content="A bug.",
        source="test",
        confidence=0.8,
        tags=["bug"],
    ))
    report = audit(store)
    assert report.total == 2
    assert report.by_type["repo_fact"] == 1
    assert report.by_type["bug_memory"] == 1
    assert report.by_status["active"] == 2
    assert report.top_tags == [("api", 1), ("bug", 1)] or report.top_tags == [("bug", 1), ("api", 1)]


def test_audit_detects_low_importance_and_obsolete(store):
    low = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Low",
        content="Low importance.",
        source="test",
        confidence=0.9,
        tags=["low"],
    )
    low.metadata["importance"] = "low"
    obsolete = MemoryItem(
        type=MemoryItemType.ARCHITECTURE_DECISION,
        title="Old decision",
        content="Deprecated.",
        status=MemoryItemStatus.OBSOLETE,
        source="test",
        confidence=0.9,
    )
    store.add(low)
    store.add(obsolete)
    report = audit(store)
    assert report.low_importance_count == 1
    assert report.obsolete_or_replaced_count == 1


def test_audit_flags_missing_source_and_confidence(store):
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="No source",
        content="x" * 50,
        source="",
        confidence=0.05,
    ))
    report = audit(store)
    assert len(report.without_source) == 1
    assert len(report.without_confidence) == 1


def test_audit_detects_content_extremes(store):
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Short",
        content="ab",
        source="test",
        confidence=0.9,
    ))
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Long",
        content="x" * 5000,
        source="test",
        confidence=0.9,
    ))
    report = audit(store)
    assert len(report.content_too_short) == 1
    assert len(report.content_too_long) == 1


def test_audit_detects_duplicates(store):
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Same",
        content="Same content.",
        source="test",
        confidence=0.9,
        tags=["dup"],
    ))
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Same",
        content="Same content.",
        source="test",
        confidence=0.9,
        tags=["dup"],
    ))
    report = audit(store)
    assert len(report.potential_duplicates) >= 1


def test_audit_no_destructive_changes_without_apply(store):
    store.add(MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="To keep",
        content="Keep me.",
        source="test",
        confidence=0.9,
    ))
    report = audit(store)
    assert report.dry_run is True
    assert report.removed_count == 0
    assert store.count() == 1
