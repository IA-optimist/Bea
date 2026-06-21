"""Tests for core.memory.memory_item and core.memory.operational_memory."""
from __future__ import annotations

import pytest

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType
from core.memory.operational_memory import OperationalMemoryStore


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "op_mem.db"
    return OperationalMemoryStore(db_path=str(db))


@pytest.fixture
def sample_item():
    return MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Facade v1",
        content="api/routes/v1.py is the canonical v1 facade.",
        related_files=["api/routes/v1.py"],
        related_tests=["tests/api/test_routes.py"],
        tags=["api", "v1"],
        confidence=0.95,
        source="test",
    )


def test_memory_item_to_dict_roundtrip(sample_item):
    data = sample_item.to_dict()
    restored = MemoryItem.from_dict(data)
    assert restored.id == sample_item.id
    assert restored.type == MemoryItemType.REPO_FACT
    assert restored.status == MemoryItemStatus.ACTIVE
    assert restored.is_usable() is True
    assert restored.is_risk() is False


def test_memory_item_obsolete_not_usable():
    item = MemoryItem(
        type=MemoryItemType.BUG_MEMORY,
        title="Old bug",
        content="Something bad.",
        status=MemoryItemStatus.OBSOLETE,
    )
    assert item.is_usable() is False


def test_memory_item_dangerous_is_risk():
    item = MemoryItem(
        type=MemoryItemType.RISK,
        title="Risk",
        content="Be careful.",
        status=MemoryItemStatus.DANGEROUS,
    )
    assert item.is_risk() is True


def test_store_add_and_get(store, sample_item):
    item_id = store.add(sample_item)
    retrieved = store.get(item_id)
    assert retrieved is not None
    assert retrieved.title == sample_item.title
    assert retrieved.related_files == ["api/routes/v1.py"]


def test_store_search_by_type(store, sample_item):
    store.add(sample_item)
    results = store.search(type=MemoryItemType.REPO_FACT)
    assert len(results) == 1
    assert results[0].title == sample_item.title


def test_store_search_by_status(store, sample_item):
    store.add(sample_item)
    item2 = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Deprecated fact",
        content="Old.",
        status=MemoryItemStatus.OBSOLETE,
    )
    store.add(item2)
    active = store.search(status=MemoryItemStatus.ACTIVE)
    assert len(active) == 1
    assert active[0].status == MemoryItemStatus.ACTIVE


def test_store_search_by_related_files(store, sample_item):
    store.add(sample_item)
    results = store.search(related_files=["api/routes/v1.py"])
    assert len(results) == 1
    assert results[0].id == sample_item.id


def test_store_search_by_tags(store, sample_item):
    store.add(sample_item)
    results = store.search(tags=["api"])
    assert len(results) == 1
    results = store.search(tags=["v1"])
    assert len(results) == 1
    results = store.search(tags=["missing"])
    assert len(results) == 0


def test_store_text_search(store, sample_item):
    store.add(sample_item)
    results = store.search(text_query="canonical v1 facade")
    assert len(results) == 1


def test_store_obsolete_deprioritized(store, sample_item):
    store.add(sample_item)
    obsolete = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="Obsolete fact",
        content="This used to be the canonical v1 facade.",
        status=MemoryItemStatus.OBSOLETE,
        confidence=1.0,
    )
    store.add(obsolete)
    results = store.search(type=MemoryItemType.REPO_FACT, text_query="canonical v1 facade")
    assert results[0].id == sample_item.id  # active comes first


def test_store_supersede(store, sample_item):
    old_id = store.add(sample_item)
    new_item = MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title="New facade",
        content="New canonical v1 facade.",
    )
    new_id = store.add(new_item)
    assert store.supersede(old_id, new_id) is True
    old = store.get(old_id)
    assert old.status == MemoryItemStatus.OBSOLETE
    assert old.superseded_by == new_id
    new = store.get(new_id)
    assert old_id in new.supersedes


def test_store_by_file(store, sample_item):
    store.add(sample_item)
    results = store.by_file("api/routes/v1.py")
    assert len(results) == 1


def test_store_by_test(store, sample_item):
    store.add(sample_item)
    results = store.by_test("tests/api/test_routes.py")
    assert len(results) == 1


def test_store_stats(store, sample_item):
    store.add(sample_item)
    stats = store.stats()
    assert stats["total"] == 1
    assert stats["persistent"] is True
    assert stats["by_type"][MemoryItemType.REPO_FACT.value] == 1
