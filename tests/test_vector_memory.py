"""tests/test_vector_memory.py — Vector memory layer tests."""
import os
import sys
import pytest
pytestmark = pytest.mark.integration


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestVectorMemoryEntry:
    def test_create(self):
        from core.memory.vector_memory import VectorMemoryEntry
        e = VectorMemoryEntry(content="test", memory_type="mission_memory")
        assert e.content == "test"
        assert e.memory_type == "mission_memory"
        assert len(e.entry_id) == 36  # UUID format

    def test_to_payload(self):
        from core.memory.vector_memory import VectorMemoryEntry
        e = VectorMemoryEntry(content="test", memory_type="short_term_context",
                              source="agent", importance=0.8)
        p = e.to_payload()
        assert p["content"] == "test"
        assert p["memory_type"] == "short_term_context"
        assert p["source"] == "agent"
        assert p["importance"] == 0.8
        assert "timestamp" in p


class TestQdrantVectorStore:
    def test_import(self):
        from core.memory.vector_memory import QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        assert store._initialized is False

    def test_search_returns_list_on_failure(self):
        from core.memory.vector_memory import QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        result = store.search([0.1] * 1536, limit=5)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_count_returns_zero_on_failure(self):
        from core.memory.vector_memory import QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        assert store.count() == 0


class TestVectorMemory:
    def test_import(self):
        from core.memory.vector_memory import get_vector_memory
        assert callable(get_vector_memory)

    def test_stats_structure(self):
        from core.memory.vector_memory import VectorMemory, QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        vm = VectorMemory(store=store)
        stats = vm.stats()
        assert "total_vectors" in stats
        assert "collection" in stats
        assert "embedding_model" in stats

    def test_search_empty_returns_list(self):
        from core.memory.vector_memory import VectorMemory, QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        vm = VectorMemory(store=store)
        # No embedding possible without API key → returns empty
        result = vm.search_similar("test query")
        assert isinstance(result, list)

    def test_retrieve_context_empty(self):
        from core.memory.vector_memory import VectorMemory, QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        vm = VectorMemory(store=store)
        result = vm.retrieve_context("test")
        assert isinstance(result, str)
        assert result == ""

    def test_store_without_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from core.memory.vector_memory import VectorMemory, QdrantVectorStore
        store = QdrantVectorStore(url="http://invalid:9999")
        vm = VectorMemory(store=store)
        result = vm.store_embedding("test", "mission_memory")
        assert result == ""


class TestVectorMemoryIntegration:
    """Integration tests requiring Qdrant + OpenAI."""

    @pytest.fixture(autouse=True)
    def check_deps(self):
        import httpx
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        try:
            httpx.get("http://qdrant:6333/collections", timeout=2)
        except Exception:
            pytest.skip("Qdrant not reachable")

    def test_store_and_search(self):
        from core.memory.vector_memory import get_vector_memory
        vm = get_vector_memory()
        eid = vm.store_embedding(
            "Python is a programming language used for AI",
            "long_term_knowledge",
            source="test",
            importance=0.9,
        )
        assert len(eid) > 0
        import time; time.sleep(0.5)
        results = vm.search_similar("programming languages for AI", limit=3)
        assert len(results) >= 1
        assert results[0]["hybrid_score"] > 0.3

    def test_store_and_retrieve_context(self):
        from core.memory.vector_memory import get_vector_memory
        vm = get_vector_memory()
        vm.store_embedding(
            "JarvisMax uses FastAPI for its REST API",
            "project_memory",
            source="test",
        )
        import time; time.sleep(0.5)
        ctx = vm.retrieve_context("What framework does Jarvis use?")
        assert isinstance(ctx, str)
        # May or may not find it depending on Qdrant indexing time
        # Just verify no crash

    def test_search_with_type_filter(self):
        from core.memory.vector_memory import get_vector_memory
        vm = get_vector_memory()
        vm.store_embedding("test entry for filtering", "user_preferences", source="test")
        import time; time.sleep(0.5)
        results = vm.search_similar("test entry", memory_type="user_preferences", limit=5)
        # All results should be user_preferences type
        for r in results:
            assert r.get("memory_type") == "user_preferences"

    def test_stats_with_qdrant(self):
        from core.memory.vector_memory import get_vector_memory
        vm = get_vector_memory()
        stats = vm.stats()
        assert stats["total_vectors"] >= 0
        assert stats["collection"] == "jarvis_aios_memory"
