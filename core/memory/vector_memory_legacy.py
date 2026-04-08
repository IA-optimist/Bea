"""
core/memory/vector_memory.py — Vector-based semantic memory layer.

Uses Qdrant (already running in Docker stack) for embedding storage and
similarity search. Integrates with MemoryLayer for type-aware retrieval.

Architecture:
  - Embeddings via OpenAI text-embedding-3-small (same as semantic_router)
  - Qdrant collection: jarvis_aios_memory
  - Hybrid retrieval: semantic similarity + recency + importance
  - Automatic embedding on store, similarity search on retrieve
"""
from __future__ import annotations

import logging
import structlog
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = structlog.get_logger("jarvis.vector_memory")

# ── Config ───────────────────────────────────────────────────────────────────

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION = "jarvis_aios_memory"
EMBEDDING_DIM = 1536
EMBEDDING_MODEL = os.getenv("JARVIS_EMBEDDING_MODEL", "text-embedding-3-small")


# ── Embedding (shared with semantic_router) ──────────────────────────────────

def _embed(text: str) -> list[float]:
    """Get embedding vector for text. Reuses semantic_router cache."""
    try:
        from core.capabilities.semantic_router import embed_single
        return embed_single(text)
    except ImportError:
        pass
    # Direct call if semantic_router unavailable
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("No OPENAI_API_KEY for vector memory")
    resp = httpx.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


# ── Qdrant Client ────────────────────────────────────────────────────────────

class QdrantVectorStore:
    """Thin Qdrant client for vector memory operations."""

    def __init__(self, url: str = QDRANT_URL, collection: str = COLLECTION):
        self._url = url
        self._collection = collection
        self._initialized = False

    def _ensure_collection(self) -> bool:
        """Create collection if it doesn't exist."""
        if self._initialized:
            return True
        try:
            r = httpx.get(f"{self._url}/collections/{self._collection}", timeout=3)
            if r.status_code == 200:
                self._initialized = True
                return True
            # Create
            httpx.put(
                f"{self._url}/collections/{self._collection}",
                json={
                    "vectors": {"size": EMBEDDING_DIM, "distance": "Cosine"},
                    "optimizers_config": {"indexing_threshold": 100},
                },
                timeout=5,
            ).raise_for_status()
            self._initialized = True
            log.info("qdrant_collection_created", collection=self._collection)
            return True
        except Exception as e:
            log.warning("qdrant_init_failed", err=str(e)[:80])
            return False

    def store(self, point_id: str, vector: list[float], payload: dict) -> bool:
        """Store a vector point with payload."""
        if not self._ensure_collection():
            return False
        try:
            httpx.put(
                f"{self._url}/collections/{self._collection}/points",
                json={
                    "points": [{
                        "id": point_id,
                        "vector": vector,
                        "payload": payload,
                    }]
                },
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as e:
            log.warning("qdrant_store_failed", err=str(e)[:80])
            return False

    def search(self, vector: list[float], limit: int = 10,
               filters: dict | None = None) -> list[dict]:
        """Search similar vectors with optional payload filters."""
        if not self._ensure_collection():
            return []
        try:
            body: dict = {
                "vector": vector,
                "limit": limit,
                "with_payload": True,
            }
            if filters:
                body["filter"] = filters
            r = httpx.post(
                f"{self._url}/collections/{self._collection}/points/search",
                json=body,
                timeout=5,
            )
            r.raise_for_status()
            results = r.json().get("result", [])
            return [
                {
                    "id": hit["id"],
                    "score": hit["score"],
                    **hit.get("payload", {}),
                }
                for hit in results
            ]
        except Exception as e:
            log.warning("qdrant_search_failed", err=str(e)[:80])
            return []

    def count(self) -> int:
        """Get total point count."""
        try:
            r = httpx.get(f"{self._url}/collections/{self._collection}", timeout=3)
            if r.status_code == 200:
                return r.json()["result"].get("points_count", 0)
        except Exception:
            pass
        return 0

    def delete(self, point_ids: list[str]) -> bool:
        """Delete points by IDs."""
        if not self._ensure_collection():
            return False
        try:
            httpx.post(
                f"{self._url}/collections/{self._collection}/points/delete",
                json={"points": point_ids},
                timeout=5,
            ).raise_for_status()
            return True
        except Exception as e:
            log.warning("qdrant_delete_failed", err=str(e)[:80])
            return False


# ── Vector Memory Layer ──────────────────────────────────────────────────────

@dataclass
class VectorMemoryEntry:
    """Entry stored in vector memory."""
    content: str
    memory_type: str
    source: str = "system"
    mission_id: str = ""
    importance: float = 0.5
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_payload(self) -> dict:
        return {
            "content": self.content,
            "memory_type": self.memory_type,
            "source": self.source,
            "mission_id": self.mission_id,
            "importance": self.importance,
            "confidence": self.confidence,
            "tags": self.tags,
            "timestamp": self.timestamp,
        }


class VectorMemory:
    """Semantic vector memory integrated with Qdrant."""

    def __init__(self, store: QdrantVectorStore | None = None):
        self._store = store or QdrantVectorStore()

    def store_embedding(self, content: str, memory_type: str, *,
                        source: str = "system", mission_id: str = "",
                        importance: float = 0.5, confidence: float = 0.5,
                        tags: list[str] | None = None) -> str:
        """Embed and store content in vector memory."""
        entry = VectorMemoryEntry(
            content=content,
            memory_type=memory_type,
            source=source,
            mission_id=mission_id,
            importance=importance,
            confidence=confidence,
            tags=tags or [],
        )
        try:
            vector = _embed(content)
            stored = self._store.store(entry.entry_id, vector, entry.to_payload())
            if stored:
                log.debug("vector_stored", type=memory_type, id=entry.entry_id)
                return entry.entry_id
            return ""
        except Exception as e:
            log.warning("vector_store_failed", err=str(e)[:80])
            return ""

    def search_similar(self, query: str, memory_type: str = "",
                       limit: int = 5, min_score: float = 0.3) -> list[dict]:
        """Search vector memory by semantic similarity.

        Returns list of dicts with content, score, memory_type, etc.
        Applies hybrid scoring: cosine_sim * 0.6 + recency * 0.2 + importance * 0.2
        """
        try:
            query_vec = _embed(query)
        except Exception as e:
            log.warning("vector_search_embed_failed", err=str(e)[:60])
            return []

        filters = None
        if memory_type:
            filters = {
                "must": [{"key": "memory_type", "match": {"value": memory_type}}]
            }

        raw_results = self._store.search(query_vec, limit=limit * 2, filters=filters)

        # Hybrid scoring
        now = time.time()
        scored = []
        for r in raw_results:
            cosine = r.get("score", 0)
            ts = r.get("timestamp", now)
            age_hours = (now - ts) / 3600
            recency = max(0.05, 1.0 - (age_hours / 720))  # Decay over 30 days
            imp = r.get("importance", 0.5)

            hybrid_score = cosine * 0.6 + recency * 0.2 + imp * 0.2

            if hybrid_score >= min_score:
                scored.append({
                    **r,
                    "hybrid_score": round(hybrid_score, 4),
                    "cosine_score": round(cosine, 4),
                    "recency_factor": round(recency, 4),
                })

        scored.sort(key=lambda x: -x["hybrid_score"])
        return scored[:limit]

    def retrieve_context(self, query: str, memory_types: list[str] | None = None,
                         limit: int = 5) -> str:
        """Retrieve relevant context as formatted text for LLM prompts."""
        if memory_types:
            all_results = []
            per_type = max(2, limit // len(memory_types))
            for mt in memory_types:
                results = self.search_similar(query, memory_type=mt, limit=per_type)
                all_results.extend(results)
            all_results.sort(key=lambda x: -x["hybrid_score"])
            results = all_results[:limit]
        else:
            results = self.search_similar(query, limit=limit)

        if not results:
            return ""

        lines = []
        for r in results:
            score = r["hybrid_score"]
            mt = r.get("memory_type", "?")
            content = r.get("content", "")[:300]
            lines.append(f"[{mt} score={score:.2f}] {content}")

        return "\n".join(lines)

    def stats(self) -> dict:
        """Vector memory statistics."""
        return {
            "total_vectors": self._store.count(),
            "collection": COLLECTION,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM,
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: VectorMemory | None = None


def get_vector_memory() -> VectorMemory:
    global _instance
    if _instance is None:
        _instance = VectorMemory()
    return _instance
