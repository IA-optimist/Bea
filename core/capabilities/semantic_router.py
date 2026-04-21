"""
core/capabilities/semantic_router.py — LLM-based semantic capability routing.

Replaces keyword matching with embedding-based similarity + LLM classification.
Maintains backward compat: falls back to keyword matching if LLM/embeddings unavailable.

Architecture:
  1. Embed user goal + all capability descriptions at startup
  2. Cosine similarity for fast ranking
  3. Optional LLM rerank for top candidates
  4. Cache embeddings to avoid repeated API calls
  5. Configurable confidence threshold
"""
from __future__ import annotations

import hashlib
import structlog
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = structlog.get_logger("jarvis.semantic_router")


# ── Configuration ─────────────────────────────────────────────────────────────

EMBEDDING_MODEL = os.getenv("JARVIS_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536
CONFIDENCE_THRESHOLD = float(os.getenv("JARVIS_SEMANTIC_THRESHOLD", "0.25"))
MAX_CANDIDATES = 5
LLM_RERANK_ENABLED = os.getenv("JARVIS_SEMANTIC_RERANK", "false").lower() == "true"
CACHE_TTL_SECONDS = 3600  # 1 hour


# ── Embedding Cache ──────────────────────────────────────────────────────────

@dataclass
class CachedEmbedding:
    vector: list[float]
    text_hash: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > CACHE_TTL_SECONDS


class EmbeddingCache:
    """In-memory embedding cache with TTL."""

    def __init__(self):
        self._cache: dict[str, CachedEmbedding] = {}
        self._hits = 0
        self._misses = 0

    def get(self, text: str) -> Optional[list[float]]:
        key = self._key(text)
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            self._hits += 1
            return entry.vector
        if entry:
            del self._cache[key]
        self._misses += 1
        return None

    def put(self, text: str, vector: list[float]) -> None:
        key = self._key(text)
        self._cache[key] = CachedEmbedding(vector=vector, text_hash=key)

    def stats(self) -> dict:
        return {"size": len(self._cache), "hits": self._hits, "misses": self._misses}

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]


_embed_cache = EmbeddingCache()


# ── Embedding Provider ───────────────────────────────────────────────────────

def _get_openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts via OpenAI API. Returns list of vectors.
    Raises on failure (caller handles fallback)."""
    key = _get_openai_key()
    if not key:
        raise RuntimeError("No OPENAI_API_KEY for embeddings")

    # Check cache first
    results: list[Optional[list[float]]] = []
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []
    for i, t in enumerate(texts):
        cached = _embed_cache.get(t)
        results.append(cached)
        if cached is None:
            uncached_indices.append(i)
            uncached_texts.append(t)

    if uncached_texts:
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        resp = httpx.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": EMBEDDING_MODEL, "input": uncached_texts},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        # Sort by index to match input order
        data.sort(key=lambda x: x["index"])
        for j, item in enumerate(data):
            vec = item["embedding"]
            idx = uncached_indices[j]
            results[idx] = vec
            _embed_cache.put(uncached_texts[j], vec)

    return results  # type: ignore


def embed_single(text: str) -> list[float]:
    """Embed a single text string."""
    return embed_texts([text])[0]


# ── Similarity ───────────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Capability Embeddings ────────────────────────────────────────────────────

_capability_embeddings: dict[str, list[float]] = {}
_cap_embed_time: float = 0


def _ensure_capability_embeddings() -> dict[str, list[float]]:
    """Embed all capability descriptions. Cached until TTL expires."""
    global _capability_embeddings, _cap_embed_time

    if _capability_embeddings and (time.time() - _cap_embed_time) < CACHE_TTL_SECONDS:
        return _capability_embeddings

    from core.capabilities.ai_os_capabilities import AIOS_CAPABILITIES

    texts = []
    names = []
    for name, cap in AIOS_CAPABILITIES.items():
        if not cap.enabled:
            continue
        # Combine name + description + tools for richer embedding
        text = f"{name}: {cap.description}. Tools: {', '.join(cap.required_tools)}. Agent: {cap.required_agent_type}"
        texts.append(text)
        names.append(name)

    vectors = embed_texts(texts)
    _capability_embeddings = dict(zip(names, vectors))
    _cap_embed_time = time.time()
    log.info("capability_embeddings_loaded", count=len(names))
    return _capability_embeddings


# ── Match Result ─────────────────────────────────────────────────────────────

@dataclass
class SemanticMatch:
    """Result from semantic capability matching."""
    capability_name: str
    confidence: float
    method: str = "semantic"  # "semantic" | "keyword" | "rerank"

    def to_dict(self) -> dict:
        return {"capability": self.capability_name, "confidence": round(self.confidence, 4),
                "method": self.method}


# ── Main Routing ─────────────────────────────────────────────────────────────

def semantic_match_capability(goal: str, threshold: float = 0.0,
                               max_results: int = 0) -> list[SemanticMatch]:
    """
    Semantically match a user goal to AI OS capabilities.

    1. Embed goal
    2. Cosine similarity against capability embeddings
    3. Return ranked matches above threshold

    Falls back to keyword matching if embeddings fail.
    """
    thr = threshold or CONFIDENCE_THRESHOLD
    limit = max_results or MAX_CANDIDATES

    try:
        goal_vec = embed_single(goal)
        cap_vecs = _ensure_capability_embeddings()

        if not cap_vecs:
            raise RuntimeError("No capability embeddings available")

        # Compute similarities
        scores: list[tuple[str, float]] = []
        for name, vec in cap_vecs.items():
            sim = cosine_similarity(goal_vec, vec)
            if sim >= thr:
                scores.append((name, sim))

        # Sort by score descending
        scores.sort(key=lambda x: -x[1])
        matches = [SemanticMatch(capability_name=n, confidence=s) for n, s in scores[:limit]]

        if matches:
            log.info("semantic_match",
                     goal=goal[:60], top=matches[0].capability_name,
                     confidence=round(matches[0].confidence, 3),
                     count=len(matches))
            return matches

        # No matches above threshold — fall through to keyword
        log.debug("semantic_no_match_above_threshold", goal=goal[:60], threshold=thr)

    except Exception as e:
        log.warning("semantic_match_fallback", err=str(e)[:100], goal=goal[:40])

    # Fallback: keyword matching (existing behavior)
    return _keyword_fallback(goal)


def _keyword_fallback(goal: str) -> list[SemanticMatch]:
    """Fallback to keyword matching when embeddings unavailable."""
    from core.capabilities.ai_os_capabilities import match_capability
    keyword_matches = match_capability(goal)
    return [
        SemanticMatch(
            capability_name=cap.name,
            confidence=0.5,  # Keyword matches get flat 0.5 confidence
            method="keyword",
        )
        for cap in keyword_matches
    ]


# ── LLM Reranking (optional, disabled by default) ───────────────────────────

def rerank_with_llm(goal: str, candidates: list[SemanticMatch]) -> list[SemanticMatch]:
    """Use LLM to rerank semantic matches for better precision.
    Only called when JARVIS_SEMANTIC_RERANK=true."""
    if not LLM_RERANK_ENABLED or len(candidates) <= 1:
        return candidates

    try:
        from core.llm_factory import LLMFactory
        llm = LLMFactory().get_llm("fast")

        cap_list = "\n".join(
            f"- {m.capability_name} (similarity={m.confidence:.2f})"
            for m in candidates
        )
        prompt = (
            f"User goal: \"{goal}\"\n\n"
            f"Candidate capabilities:\n{cap_list}\n\n"
            f"Rank these capabilities by relevance to the goal. "
            f"Return ONLY a JSON list of objects: "
            f'[{{"name": "cap_name", "score": 0.0-1.0}}]'
        )
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)

        import json
        # Extract JSON from response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            ranked = json.loads(text[start:end])
            result = []
            for item in ranked:
                name = item.get("name", "")
                score = float(item.get("score", 0))
                result.append(SemanticMatch(
                    capability_name=name, confidence=score, method="rerank"
                ))
            if result:
                log.info("llm_reranked", count=len(result))
                return result

    except Exception as e:
        log.warning("llm_rerank_failed", err=str(e)[:80])

    return candidates  # Return unmodified on failure


# ── Diagnostics ──────────────────────────────────────────────────────────────

def router_stats() -> dict:
    """Stats for monitoring endpoint."""
    return {
        "cache": _embed_cache.stats(),
        "capability_embeddings_loaded": len(_capability_embeddings),
        "embedding_model": EMBEDDING_MODEL,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "rerank_enabled": LLM_RERANK_ENABLED,
    }
