"""
Tests — MemoryFacade
Core functionality tests for unified memory interface.

Coverage:
    1. Memory entry creation and validation
    2. Backend routing based on content type
    3. Store operations with fallback
    4. Search across multiple backends
    5. Get recent entries
    6. Backend health checking
    7. JSONL fallback mechanism
"""
import sys
import os
import tempfile
import types
import pytest
import json
import time
from pathlib import Path

# Bootstrap path & mock structlog
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import structlog  # noqa: F401
except ImportError:
    mock_sl = types.ModuleType("structlog")
    mock_sl.get_logger = lambda *a, **k: types.SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules["structlog"] = mock_sl


# ═══════════════════════════════════════════════════════════════
# MEMORY ENTRY TESTS
# ═══════════════════════════════════════════════════════════════

def test_memory_entry_creation():
    """MemoryEntry should initialize with proper defaults."""
    from core.memory_facade import MemoryEntry
    
    entry = MemoryEntry(
        content="Test content",
        content_type="solution",
        tags=["test", "example"],
    )
    
    assert entry.content == "Test content"
    assert entry.content_type == "solution"
    assert entry.tags == ["test", "example"]
    assert entry.score == 0.0
    assert entry.source == ""
    assert isinstance(entry.timestamp, float)
    print("[OK] test_memory_entry_creation")


def test_memory_entry_to_dict():
    """MemoryEntry.to_dict() should serialize properly."""
    from core.memory_facade import MemoryEntry
    
    entry = MemoryEntry(
        content="Test content" * 500,  # Long content
        content_type="solution",
        tags=["test"],
        source="memory_toolkit",
        score=0.85,
        entry_id="test-123",
    )
    
    d = entry.to_dict()
    
    assert len(d["content"]) <= 2000  # Should be truncated
    assert d["content_type"] == "solution"
    assert d["tags"] == ["test"]
    assert d["source"] == "memory_toolkit"
    assert d["score"] == 0.85
    assert d["entry_id"] == "test-123"
    print("[OK] test_memory_entry_to_dict")


# ═══════════════════════════════════════════════════════════════
# BACKEND STATUS TESTS
# ═══════════════════════════════════════════════════════════════

def test_backend_status_creation():
    """BackendStatus should track availability."""
    from core.memory_facade import _BackendStatus
    
    status = _BackendStatus("memory_bus")
    
    assert status.name == "memory_bus"
    assert status.available is False
    assert status.error == ""
    print("[OK] test_backend_status_creation")


def test_backend_status_to_dict():
    """BackendStatus.to_dict() should serialize properly."""
    from core.memory_facade import _BackendStatus
    
    status = _BackendStatus("memory_toolkit")
    status.available = True
    status.error = "Connection failed"
    status.last_check = 1234567890.0
    
    d = status.to_dict()
    
    assert d["name"] == "memory_toolkit"
    assert d["available"] is True
    assert d["error"] == "Connection failed"
    assert d["last_check"] == 1234567890.0
    print("[OK] test_backend_status_to_dict")


# ═══════════════════════════════════════════════════════════════
# MEMORY FACADE INITIALIZATION TESTS
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def temp_workspace():
    """Create temporary workspace directory."""
    tmp_dir = tempfile.mkdtemp()
    yield tmp_dir
    # Cleanup handled by OS


@pytest.fixture
def memory_facade(temp_workspace):
    """Create MemoryFacade instance with temp workspace."""
    from core.memory_facade import MemoryFacade
    return MemoryFacade(workspace_dir=temp_workspace)


def test_memory_facade_initialization(temp_workspace):
    """MemoryFacade should initialize with proper structure."""
    from core.memory_facade import MemoryFacade
    
    facade = MemoryFacade(workspace_dir=temp_workspace)
    
    assert facade._workspace == Path(temp_workspace)
    assert facade._fallback_path.exists() is False  # Not created until write
    assert len(facade._backends) > 0
    assert "memory_bus" in facade._backends
    assert "knowledge_jsonl" in facade._backends
    assert facade._backends["knowledge_jsonl"].available is True
    print("[OK] test_memory_facade_initialization")


# ═══════════════════════════════════════════════════════════════
# CONTENT TYPE ROUTING TESTS
# ═══════════════════════════════════════════════════════════════

def test_content_types_defined():
    """All content types should be properly defined."""
    from core.memory_facade import CONTENT_TYPES
    
    expected_types = {
        "solution", "error", "patch", "decision", "pattern",
        "objective", "mission_outcome", "knowledge", "failure", "general"
    }
    
    assert CONTENT_TYPES == expected_types
    print("[OK] test_content_types_defined")


def test_routing_table_defined():
    """Routing table should map content types to backends."""
    from core.memory_facade import _ROUTING
    
    assert "solution" in _ROUTING
    assert "memory_toolkit" in _ROUTING["solution"]
    
    assert "decision" in _ROUTING
    assert "decision_memory" in _ROUTING["decision"]
    
    assert "patch" in _ROUTING
    assert "memory_bus_patches" in _ROUTING["patch"]
    print("[OK] test_routing_table_defined")


# ═══════════════════════════════════════════════════════════════
# STORE TESTS
# ═══════════════════════════════════════════════════════════════

def test_store_to_jsonl_fallback(memory_facade):
    """Store should write to JSONL fallback when backends unavailable."""
    result = memory_facade.store(
        content="Test solution",
        content_type="solution",
        tags=["test", "example"],
    )
    
    assert result["ok"] is True
    assert "backend" in result
    assert "entry_id" in result
    
    # Verify JSONL file was created
    assert memory_facade._fallback_path.exists()
    
    # Verify content
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    assert data["content"] == "Test solution"
    assert data["type"] == "solution"
    assert data["tags"] == ["test", "example"]
    print("[OK] test_store_to_jsonl_fallback")


def test_store_invalid_content_type(memory_facade):
    """Invalid content type should default to 'general'."""
    result = memory_facade.store(
        content="Test content",
        content_type="invalid_type",
    )
    
    assert result["ok"] is True
    
    # Check that it was stored with 'general' type
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    assert data["type"] == "general"
    print("[OK] test_store_invalid_content_type")


def test_store_with_metadata(memory_facade):
    """Store should handle metadata properly."""
    result = memory_facade.store(
        content="Test content",
        content_type="solution",
        tags=["test"],
        metadata={"source": "test", "confidence": 0.9},
    )
    
    assert result["ok"] is True
    
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    assert "metadata" in data
    assert data["metadata"]["source"] == "test"
    print("[OK] test_store_with_metadata")


# ═══════════════════════════════════════════════════════════════
# SEARCH TESTS
# ═══════════════════════════════════════════════════════════════

def test_search_empty_results(memory_facade):
    """Search with no stored data should return empty list."""
    results = memory_facade.search("test query", top_k=5)
    
    assert isinstance(results, list)
    assert len(results) == 0
    print("[OK] test_search_empty_results")


def test_search_jsonl_basic(memory_facade):
    """Search should find results in JSONL fallback."""
    # Store some test data
    memory_facade.store("Python authentication bug fixed", content_type="solution", tags=["python", "auth"])
    memory_facade.store("Database connection improved", content_type="solution", tags=["database"])
    memory_facade.store("API endpoint created", content_type="solution", tags=["api"])
    
    # Search for authentication
    results = memory_facade.search("authentication", top_k=5)
    
    assert len(results) > 0
    assert any("authentication" in r.content.lower() for r in results)
    print("[OK] test_search_jsonl_basic")


def test_search_with_content_type_filter(memory_facade):
    """Search should filter by content type."""
    memory_facade.store("Error solution", content_type="error", tags=["error"])
    memory_facade.store("Patch applied", content_type="patch", tags=["patch"])
    memory_facade.store("Decision made", content_type="decision", tags=["decision"])
    
    results = memory_facade.search("solution", content_type="error", top_k=5)
    
    # All results should be of type 'error'
    for result in results:
        assert result.content_type == "error"
    print("[OK] test_search_with_content_type_filter")


def test_search_scoring(memory_facade):
    """Search results should be scored and sorted."""
    memory_facade.store("authentication bug fix", content_type="solution")
    memory_facade.store("unrelated content", content_type="solution")
    
    results = memory_facade.search("authentication bug", top_k=5)
    
    if len(results) > 1:
        # Results should be sorted by score descending
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)
    print("[OK] test_search_scoring")


def test_search_deduplication(memory_facade):
    """Search should deduplicate identical results."""
    # Store duplicate content
    content = "Identical authentication fix"
    memory_facade.store(content, content_type="solution")
    memory_facade.store(content, content_type="solution")
    memory_facade.store(content, content_type="solution")
    
    results = memory_facade.search("authentication", top_k=10)
    
    # Should only return 1 result despite 3 stores
    assert len(results) == 1
    print("[OK] test_search_deduplication")


def test_search_top_k_limit(memory_facade):
    """Search should respect top_k limit."""
    # Store many entries
    for i in range(10):
        memory_facade.store(f"Test solution {i}", content_type="solution", tags=["test"])
    
    results = memory_facade.search("test", top_k=3)
    
    assert len(results) <= 3
    print("[OK] test_search_top_k_limit")


# ═══════════════════════════════════════════════════════════════
# GET RECENT TESTS
# ═══════════════════════════════════════════════════════════════

def test_get_recent_empty(memory_facade):
    """get_recent with no data should return empty list."""
    results = memory_facade.get_recent(n=10)
    
    assert isinstance(results, list)
    assert len(results) == 0
    print("[OK] test_get_recent_empty")


def test_get_recent_all_types(memory_facade):
    """get_recent should return entries of all types."""
    memory_facade.store("Solution 1", content_type="solution")
    memory_facade.store("Error 1", content_type="error")
    memory_facade.store("Decision 1", content_type="decision")
    
    results = memory_facade.get_recent(n=10)
    
    assert len(results) == 3
    content_types = {r.content_type for r in results}
    assert "solution" in content_types
    assert "error" in content_types
    assert "decision" in content_types
    print("[OK] test_get_recent_all_types")


def test_get_recent_with_type_filter(memory_facade):
    """get_recent should filter by content type."""
    memory_facade.store("Solution 1", content_type="solution")
    memory_facade.store("Solution 2", content_type="solution")
    memory_facade.store("Error 1", content_type="error")
    
    results = memory_facade.get_recent(content_type="solution", n=10)
    
    assert len(results) == 2
    assert all(r.content_type == "solution" for r in results)
    print("[OK] test_get_recent_with_type_filter")


def test_get_recent_limit(memory_facade):
    """get_recent should respect n limit."""
    for i in range(10):
        memory_facade.store(f"Entry {i}", content_type="solution")
    
    results = memory_facade.get_recent(n=5)
    
    assert len(results) == 5
    print("[OK] test_get_recent_limit")


def test_get_recent_ordering(memory_facade):
    """get_recent should return most recent entries first."""
    memory_facade.store("First", content_type="solution")
    time.sleep(0.01)  # Ensure different timestamps
    memory_facade.store("Second", content_type="solution")
    time.sleep(0.01)
    memory_facade.store("Third", content_type="solution")
    
    results = memory_facade.get_recent(n=10)
    
    # Most recent should be first
    assert results[0].content == "Third"
    assert results[-1].content == "First"
    print("[OK] test_get_recent_ordering")


# ═══════════════════════════════════════════════════════════════
# HEALTH CHECK TESTS
# ═══════════════════════════════════════════════════════════════

def test_health_check_structure(memory_facade):
    """health() should return proper structure."""
    health = memory_facade.health()
    
    # health() returns dict of backend_name: status_dict
    assert isinstance(health, dict)
    assert len(health) > 0
    # Check that it contains expected backends
    assert "knowledge_jsonl" in health
    print("[OK] test_health_check_structure")


def test_health_check_backends(memory_facade):
    """health() should report on all backends."""
    health = memory_facade.health()
    
    # health is a dict with backend names as keys
    assert "memory_bus" in health
    assert "memory_toolkit" in health
    assert "knowledge_jsonl" in health
    print("[OK] test_health_check_backends")


def test_health_check_jsonl_always_available(memory_facade):
    """knowledge_jsonl should always be marked as available."""
    health = memory_facade.health()
    
    # Access backend status directly from dict
    jsonl_status = health.get("knowledge_jsonl", {})
    assert jsonl_status.get("available") is True
    print("[OK] test_health_check_jsonl_always_available")


# ═══════════════════════════════════════════════════════════════
# JSONL FALLBACK TESTS
# ═══════════════════════════════════════════════════════════════

def test_jsonl_content_truncation(memory_facade):
    """JSONL fallback should truncate long content."""
    long_content = "x" * 10000
    memory_facade.store(long_content, content_type="solution")
    
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    
    assert len(data["content"]) <= 3000
    print("[OK] test_jsonl_content_truncation")


def test_jsonl_tags_truncation(memory_facade):
    """JSONL fallback should truncate excessive tags."""
    many_tags = [f"tag{i}" for i in range(20)]
    memory_facade.store("Test", content_type="solution", tags=many_tags)
    
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    
    assert len(data["tags"]) <= 10
    print("[OK] test_jsonl_tags_truncation")


def test_jsonl_metadata_truncation(memory_facade):
    """JSONL fallback should truncate metadata."""
    large_metadata = {f"key{i}": "x" * 500 for i in range(20)}
    memory_facade.store("Test", content_type="solution", metadata=large_metadata)
    
    content = memory_facade._fallback_path.read_text()
    data = json.loads(content.strip())
    
    assert len(data["metadata"]) <= 10
    for value in data["metadata"].values():
        assert len(value) <= 200
    print("[OK] test_jsonl_metadata_truncation")


# ═══════════════════════════════════════════════════════════════
# BACKEND MOCKING TESTS
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="requires Qdrant")
def test_store_with_memory_toolkit():
    """Store should route to memory_toolkit when available."""
    # Requires actual memory_toolkit backend
    pass


@pytest.mark.skip(reason="requires Qdrant")
def test_search_with_memory_bus():
    """Search should query memory_bus when available."""
    # Requires actual memory_bus backend with Qdrant
    pass


@pytest.mark.skip(reason="requires external services")
def test_store_with_knowledge_memory():
    """Store should route to knowledge_memory when available."""
    # Requires actual knowledge_memory backend
    pass


# ═══════════════════════════════════════════════════════════════
# RUN ALL TESTS
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
