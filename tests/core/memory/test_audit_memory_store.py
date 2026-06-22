"""Tests for audit_memory_store.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.audit_memory_store import audit, privacy_scan, _check_privacy, main as audit_main
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


# --------------------------------------------------------------------------- #
# Privacy scan tests
# --------------------------------------------------------------------------- #

def _make_item(title, content, tags=None, source="test"):
    return MemoryItem(
        type=MemoryItemType.REPO_FACT,
        title=title,
        content=content,
        tags=tags or [],
        source=source,
    )


def test_privacy_scan_detects_email(store):
    item_id = store.add(_make_item(
        "Contact info", "Reach me at john.doe@example.com for details.",
    ))
    report = privacy_scan(store)
    flagged_ids = [p["id"] for p in report["private_items"]]
    assert item_id in flagged_ids


def test_privacy_scan_detects_fake_token(store):
    item_id = store.add(_make_item(
        "API key", "Use sk-FAKE1234567890ABCDEF for testing.",
    ))
    report = privacy_scan(store)
    flagged_ids = [p["id"] for p in report["private_items"]]
    assert item_id in flagged_ids


def test_privacy_scan_detects_private_joke(store):
    item_id = store.add(_make_item(
        "Inside joke", "Why did the chicken cross the road?",
        tags=["private_joke", "humour"],
    ))
    report = privacy_scan(store)
    flagged_ids = [p["id"] for p in report["private_items"]]
    assert item_id in flagged_ids


def test_privacy_scan_detects_personal_fun_fact(store):
    item_id = store.add(_make_item(
        "Personal fun fact", "I love cats and my favorite color is blue.",
        tags=["personal", "fun_fact"],
    ))
    report = privacy_scan(store)
    flagged_ids = [p["id"] for p in report["private_items"]]
    assert item_id in flagged_ids


def test_privacy_scan_clean_project_fact_not_flagged(store):
    item_id = store.add(_make_item(
        "Architecture decision", "api/routes/v1.py is the canonical v1 facade.",
        tags=["api", "v1", "canonical"],
        source="audit/architecture",
    ))
    report = privacy_scan(store)
    flagged_ids = [p["id"] for p in report["private_items"]]
    assert item_id not in flagged_ids


def test_privacy_scan_dry_run_no_modification(store):
    store.add(_make_item("Test", "content"))
    count_before = store.count()
    privacy_scan(store)
    assert store.count() == count_before


def test_apply_always_aborts(store):
    """--apply must always abort with exit code 2, no bypass."""
    exit_code = audit_main(["--apply"])
    assert exit_code == 2


def test_privacy_scan_json_stable(store):
    store.add(_make_item("Item 1", "content 1"))
    report = privacy_scan(store)
    json_str = json.dumps(report, sort_keys=True)
    parsed = json.loads(json_str)
    assert parsed["mode"] == "dry-run"
    assert "api_key" not in json_str.lower()
    assert "sk-" not in json_str.lower()


def test_privacy_scan_sample_duplicates(store):
    """Two items with same title+content+source should be detected as duplicates."""
    store.add(_make_item("Same title", "Same content.", source="same_source", tags=["dup"]))
    store.add(_make_item("Same title", "Same content.", source="same_source", tags=["dup"]))
    report = privacy_scan(store, sample_duplicates=10)
    assert report["duplicate_group_count"] >= 1


# --------------------------------------------------------------------------- #
# Seed verdict tests
# --------------------------------------------------------------------------- #

def test_seed_report_detects_private_joke():
    """The seed_bea_memory.py --report should detect private_joke in the seed."""
    from scripts.seed_bea_memory import report_seed_verdict
    import io

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exit_code = report_seed_verdict()
    finally:
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

    assert exit_code == 1
    assert "public_safe: False" in output
    assert "private_joke" in output.lower()
