"""tests/test_semantic_routing.py — Semantic capability routing tests."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest


class TestSemanticRouter:
    """Tests for core.capabilities.semantic_router."""

    def test_import(self):
        from core.capabilities.semantic_router import semantic_match_capability
        assert callable(semantic_match_capability)

    def test_keyword_fallback_when_no_key(self, monkeypatch):
        """Falls back to keyword matching if OPENAI_API_KEY missing."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from core.capabilities.semantic_router import _keyword_fallback
        matches = _keyword_fallback("research market trends")
        assert len(matches) >= 1
        assert matches[0].method == "keyword"
        assert matches[0].confidence == 0.5

    def test_semantic_match_returns_list(self):
        """semantic_match_capability always returns a list."""
        from core.capabilities.semantic_router import semantic_match_capability
        result = semantic_match_capability("analyze code quality")
        assert isinstance(result, list)

    def test_semantic_match_dataclass(self):
        from core.capabilities.semantic_router import SemanticMatch
        m = SemanticMatch(capability_name="test", confidence=0.85, method="semantic")
        d = m.to_dict()
        assert d["capability"] == "test"
        assert d["confidence"] == 0.85
        assert d["method"] == "semantic"

    def test_cosine_similarity(self):
        from core.capabilities.semantic_router import cosine_similarity
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0)
        c = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, c) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        from core.capabilities.semantic_router import cosine_similarity
        assert cosine_similarity([0, 0, 0], [1, 0, 0]) == 0.0

    def test_embedding_cache(self):
        from core.capabilities.semantic_router import EmbeddingCache
        cache = EmbeddingCache()
        assert cache.get("test") is None
        cache.put("test", [0.1, 0.2, 0.3])
        assert cache.get("test") == [0.1, 0.2, 0.3]
        assert cache.stats()["hits"] == 1
        assert cache.stats()["misses"] == 1

    def test_embedding_cache_ttl(self, monkeypatch):
        from core.capabilities.semantic_router import EmbeddingCache
        cache = EmbeddingCache()
        cache.put("test", [0.1])
        # Force expiry
        key = cache._key("test")
        cache._cache[key].created_at = 0  # epoch → expired
        assert cache.get("test") is None

    def test_router_stats(self):
        from core.capabilities.semantic_router import router_stats
        stats = router_stats()
        assert "cache" in stats
        assert "embedding_model" in stats
        assert "confidence_threshold" in stats

    def test_keyword_fallback_market_research(self):
        from core.capabilities.semantic_router import _keyword_fallback
        matches = _keyword_fallback("research competitors in AI")
        names = [m.capability_name for m in matches]
        assert "market_research" in names

    def test_keyword_fallback_code_generation(self):
        from core.capabilities.semantic_router import _keyword_fallback
        matches = _keyword_fallback("generate python module for data processing")
        names = [m.capability_name for m in matches]
        assert "code_generation" in names

    def test_keyword_fallback_system_diagnosis(self):
        from core.capabilities.semantic_router import _keyword_fallback
        matches = _keyword_fallback("diagnose server performance issues")
        names = [m.capability_name for m in matches]
        assert "system_diagnosis" in names

    def test_semantic_match_threshold(self):
        """Keyword fallback always returns results regardless of threshold."""
        from core.capabilities.semantic_router import _keyword_fallback
        result = _keyword_fallback("analyze code")
        assert isinstance(result, list)
        # All keyword results have 0.5 confidence
        for m in result:
            assert m.confidence == 0.5


class TestSemanticRouterIntegration:
    """Integration tests requiring OPENAI_API_KEY."""

    @pytest.fixture(autouse=True)
    def check_api_key(self):
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

    def test_embed_texts(self):
        from core.capabilities.semantic_router import embed_texts
        vecs = embed_texts(["hello world"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 1536

    def test_embed_multiple(self):
        from core.capabilities.semantic_router import embed_texts
        vecs = embed_texts(["hello", "world", "test"])
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == 1536

    def test_semantic_match_with_embeddings(self):
        from core.capabilities.semantic_router import semantic_match_capability
        matches = semantic_match_capability("research market trends and competitors")
        assert len(matches) >= 1
        assert matches[0].method == "semantic"
        assert matches[0].confidence > 0.3

    def test_semantic_match_code_goal(self):
        from core.capabilities.semantic_router import semantic_match_capability
        matches = semantic_match_capability("write a Python function to sort data")
        names = [m.capability_name for m in matches]
        assert "code_generation" in names

    def test_semantic_match_confidence_ordering(self):
        from core.capabilities.semantic_router import semantic_match_capability
        matches = semantic_match_capability("audit the repository for security issues")
        if len(matches) >= 2:
            assert matches[0].confidence >= matches[1].confidence
