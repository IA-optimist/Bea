"""
memory_system.py — JarvisMax Memory System
Architecture à 3 niveaux inspirée du cerveau humain.

Niveau 1 — Mémoire de travail  : Redis (contexte session, TTL court)
Niveau 2 — Mémoire épisodique  : Qdrant collection "episodes" (événements datés)
Niveau 3 — Mémoire sémantique  : Qdrant collection "semantic" (faits permanents)

Auteur   : sous-agent JarvisMax (2026-04-09)
Python   : 3.10+
Deps     : qdrant-client, httpx, redis, tiktoken (optionnel)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

# ── Optional deps (graceful degradation) ──────────────────────────────────────
try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchRange,
        MatchValue,
        PointStruct,
        Range,
        VectorParams,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logging.warning("qdrant-client not installed — Qdrant features disabled")

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis not installed — working-memory will use in-process dict")

# ── Config ─────────────────────────────────────────────────────────────────────

QDRANT_URL        = "http://qdrant:6333"
OLLAMA_URL        = "http://localhost:11434"
EMBED_MODEL       = "nomic-embed-text"
EMBED_DIM         = 768          # nomic-embed-text output dim
REDIS_URL         = "redis://localhost:6379"
WORKING_TTL_SEC   = 3600         # 1 hour — working memory expiry
EPISODE_COLL      = "jarvis_episodes"
SEMANTIC_COLL     = "jarvis_semantic"

MemoryType = Literal["working", "episode", "semantic"]

logger = logging.getLogger("jarvis.memory")


# ── Embedding helper ───────────────────────────────────────────────────────────

async def embed(text: str) -> list[float]:
    """
    Get embedding from Ollama nomic-embed-text.
    Falls back to a deterministic hash-based pseudo-vector if Ollama is down.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
    except Exception as exc:
        logger.warning("Ollama embed failed (%s) — using hash fallback", exc)
        return _hash_embed(text)


def _hash_embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic pseudo-embedding via repeated SHA-256 hashing."""
    seed = text.encode()
    floats: list[float] = []
    i = 0
    while len(floats) < dim:
        h = hashlib.sha256(seed + i.to_bytes(4, "little")).digest()
        floats.extend((b / 255.0) - 0.5 for b in h)
        i += 1
    return floats[:dim]


# ── LLM helper (for summarisation) ────────────────────────────────────────────

async def llm_complete(prompt: str, model: str = "mistral") -> str:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error("LLM completion failed: %s", exc)
        return f"[LLM unavailable: {exc}]"


# ── Working memory (Level 1) ───────────────────────────────────────────────────

class WorkingMemory:
    """
    Fast, ephemeral, session-scoped context.
    Backend : Redis with TTL (falls back to in-process dict).
    Key space: jarvis:wm:<session_id>
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._key = f"jarvis:wm:{session_id}"
        self._local: dict[str, Any] = {}   # fallback when Redis unavailable
        self._redis: Any = None

    async def _get_redis(self):
        if not REDIS_AVAILABLE:
            return None
        if self._redis is None:
            try:
                self._redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            except Exception as exc:
                logger.warning("Redis unavailable: %s", exc)
        return self._redis

    async def set(self, key: str, value: Any, ttl: int = WORKING_TTL_SEC) -> None:
        r = await self._get_redis()
        if r:
            await r.hset(self._key, key, json.dumps(value))
            await r.expire(self._key, ttl)
        else:
            self._local[key] = value

    async def get(self, key: str) -> Any | None:
        r = await self._get_redis()
        if r:
            raw = await r.hget(self._key, key)
            return json.loads(raw) if raw else None
        return self._local.get(key)

    async def get_all(self) -> dict[str, Any]:
        r = await self._get_redis()
        if r:
            raw = await r.hgetall(self._key)
            return {k: json.loads(v) for k, v in raw.items()}
        return dict(self._local)

    async def clear(self) -> None:
        r = await self._get_redis()
        if r:
            await r.delete(self._key)
        self._local.clear()


# ── Qdrant bootstrap ───────────────────────────────────────────────────────────

async def _ensure_collection(client: "AsyncQdrantClient", name: str) -> None:
    existing = [c.name for c in (await client.get_collections()).collections]
    if name not in existing:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", name)


# ── Main MemorySystem ──────────────────────────────────────────────────────────

@dataclass
class MemorySystem:
    """
    Three-level memory system for JarvisMax.

    Levels
    ------
    working   → WorkingMemory (Redis / in-process dict, TTL-based)
    episode   → Qdrant "jarvis_episodes"  (time-tagged events, medium term)
    semantic  → Qdrant "jarvis_semantic"  (distilled facts, long term)
    """

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    _wm: WorkingMemory = field(init=False)
    _qdrant: Any = field(init=False, default=None)

    def __post_init__(self):
        self._wm = WorkingMemory(self.session_id)

    # ── Qdrant client (lazy) ───────────────────────────────────────────────────

    async def _get_qdrant(self) -> "AsyncQdrantClient | None":
        if not QDRANT_AVAILABLE:
            return None
        if self._qdrant is None:
            try:
                self._qdrant = AsyncQdrantClient(url=QDRANT_URL)
                await _ensure_collection(self._qdrant, EPISODE_COLL)
                await _ensure_collection(self._qdrant, SEMANTIC_COLL)
            except Exception as exc:
                logger.error("Qdrant unavailable: %s", exc)
                self._qdrant = None
        return self._qdrant

    # ── store ──────────────────────────────────────────────────────────────────

    async def store(
        self,
        content: str,
        importance: float,
        memory_type: MemoryType,
        *,
        metadata: dict | None = None,
        mission_id: str | None = None,
    ) -> str:
        """
        Store a memory.

        Parameters
        ----------
        content      : Text to remember.
        importance   : 0.0–1.0. Items below 0.3 are usually noise.
        memory_type  : "working" | "episode" | "semantic"
        metadata     : Extra key-value pairs stored alongside the point.
        mission_id   : Groups related episodes (e.g. a task run).

        Returns
        -------
        memory_id (str)
        """
        memory_id = str(uuid.uuid4())
        now_ts = time.time()
        meta = {
            "content": content,
            "importance": importance,
            "memory_type": memory_type,
            "created_at": now_ts,
            "session_id": self.session_id,
            **(metadata or {}),
        }
        if mission_id:
            meta["mission_id"] = mission_id

        # ── Level 1 : working memory (always) ─────────────────────────────────
        if memory_type == "working":
            await self._wm.set(memory_id, meta)
            logger.debug("Working memory stored: %s", memory_id)
            return memory_id

        # ── Level 2/3 : Qdrant persistence ────────────────────────────────────
        if importance < 0.3:
            logger.debug("Skipping low-importance memory (%.2f): %s…", importance, content[:60])
            return memory_id  # discard silently

        client = await self._get_qdrant()
        if client is None:
            logger.warning("Qdrant unavailable — memory not persisted")
            return memory_id

        vector = await embed(content)
        collection = EPISODE_COLL if memory_type == "episode" else SEMANTIC_COLL

        await client.upsert(
            collection_name=collection,
            points=[PointStruct(id=memory_id, vector=vector, payload=meta)],
        )
        logger.info("Stored %s memory [imp=%.2f]: %s…", memory_type, importance, content[:80])
        return memory_id

    # ── retrieve ───────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        memory_types: list[MemoryType] | None = None,
        min_importance: float = 0.0,
        since_days: float | None = None,
    ) -> list[dict]:
        """
        Retrieve the most semantically relevant memories.

        Searches working memory (in-process), then Qdrant episode + semantic
        collections and merges results ranked by similarity × importance.

        Parameters
        ----------
        query         : Natural language query.
        top_k         : Max results to return.
        memory_types  : Filter by type (default: all).
        min_importance: Minimum importance threshold.
        since_days    : Only include memories newer than N days.

        Returns
        -------
        List of memory dicts sorted by relevance score (desc).
        """
        types = set(memory_types or ["working", "episode", "semantic"])
        results: list[dict] = []

        # ── Level 1 : scan working memory ──────────────────────────────────────
        if "working" in types:
            all_wm = await self._wm.get_all()
            for mid, mem in all_wm.items():
                if isinstance(mem, dict) and mem.get("importance", 0) >= min_importance:
                    results.append({**mem, "memory_id": mid, "score": 0.9, "source": "working"})

        # ── Level 2/3 : Qdrant semantic search ────────────────────────────────
        client = await self._get_qdrant()
        if client:
            query_vec = await embed(query)
            cutoff_ts = (time.time() - since_days * 86400) if since_days else None

            for coll, mtype in [(EPISODE_COLL, "episode"), (SEMANTIC_COLL, "semantic")]:
                if mtype not in types:
                    continue

                # Build optional filter
                must_conditions = []
                if min_importance > 0:
                    must_conditions.append(
                        FieldCondition(
                            key="importance",
                            range=Range(gte=min_importance),
                        )
                    )
                if cutoff_ts is not None:
                    must_conditions.append(
                        FieldCondition(
                            key="created_at",
                            range=Range(gte=cutoff_ts),
                        )
                    )

                qfilter = Filter(must=must_conditions) if must_conditions else None

                try:
                    hits = await client.search(
                        collection_name=coll,
                        query_vector=query_vec,
                        limit=top_k,
                        query_filter=qfilter,
                        with_payload=True,
                    )
                    for h in hits:
                        payload = h.payload or {}
                        # Boost score by importance
                        boosted = h.score * (0.5 + 0.5 * payload.get("importance", 0.5))
                        results.append({**payload, "memory_id": str(h.id), "score": boosted, "source": mtype})
                except Exception as exc:
                    logger.error("Qdrant search error on %s: %s", coll, exc)

        # Deduplicate + sort
        seen: set[str] = set()
        unique: list[dict] = []
        for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
            mid = r.get("memory_id", "")
            if mid not in seen:
                seen.add(mid)
                unique.append(r)

        return unique[:top_k]

    # ── forget ─────────────────────────────────────────────────────────────────

    async def forget(
        self,
        older_than_days: int,
        importance_below: float,
    ) -> int:
        """
        Delete old, low-importance memories from Qdrant.

        Parameters
        ----------
        older_than_days : Memories older than this (in days) are candidates.
        importance_below: Only delete if importance < this threshold.

        Returns
        -------
        Number of points deleted.
        """
        client = await self._get_qdrant()
        if client is None:
            return 0

        cutoff_ts = time.time() - older_than_days * 86400
        deleted_total = 0

        for coll in [EPISODE_COLL, SEMANTIC_COLL]:
            filt = Filter(
                must=[
                    FieldCondition(key="created_at", range=Range(lte=cutoff_ts)),
                    FieldCondition(key="importance", range=Range(lt=importance_below)),
                ]
            )
            try:
                result = await client.delete(collection_name=coll, points_selector=filt)
                deleted_total += getattr(result, "deleted", 0)
                logger.info("Forget: deleted from %s (ts<%.0f, imp<%.2f)", coll, cutoff_ts, importance_below)
            except Exception as exc:
                logger.error("Forget error on %s: %s", coll, exc)

        return deleted_total

    # ── summarize_episode ──────────────────────────────────────────────────────

    async def summarize_episode(self, mission_id: str) -> str:
        """
        Retrieve all memories for a mission and ask the LLM to produce
        a compact summary, then store it as a high-importance semantic memory.

        Parameters
        ----------
        mission_id : Identifier used when storing episode memories.

        Returns
        -------
        Summary text.
        """
        client = await self._get_qdrant()
        if client is None:
            return "[Qdrant unavailable — cannot summarise]"

        # Scroll all points for this mission
        records, _ = await client.scroll(
            collection_name=EPISODE_COLL,
            scroll_filter=Filter(
                must=[FieldCondition(key="mission_id", match=MatchValue(value=mission_id))]
            ),
            limit=200,
            with_payload=True,
        )

        if not records:
            return f"[No episodes found for mission_id={mission_id}]"

        # Sort chronologically and build prompt
        events = sorted(records, key=lambda r: (r.payload or {}).get("created_at", 0))
        bullet_list = "\n".join(
            f"- [{datetime.fromtimestamp((r.payload or {}).get('created_at', 0), tz=timezone.utc).strftime('%H:%M')}] "
            f"{(r.payload or {}).get('content', '')}"
            for r in events
        )

        prompt = (
            "You are a memory consolidation assistant.\n"
            f"Summarize the following events from mission '{mission_id}' into a compact, "
            "factual paragraph (max 150 words). Highlight key decisions, errors, and lessons.\n\n"
            f"{bullet_list}\n\nSummary:"
        )
        summary = await llm_complete(prompt)

        # Store summary as permanent semantic memory
        await self.store(
            content=f"[Episode summary: {mission_id}] {summary}",
            importance=0.9,
            memory_type="semantic",
            metadata={"source_mission_id": mission_id, "type": "episode_summary"},
        )
        logger.info("Episode summarised and stored for mission %s", mission_id)
        return summary

    # ── helpers ────────────────────────────────────────────────────────────────

    async def store_interaction(
        self,
        user_msg: str,
        assistant_msg: str,
        importance: float | None = None,
        mission_id: str | None = None,
    ) -> tuple[str, str]:
        """
        Convenience: store a full exchange as two episode memories.
        Auto-estimates importance if not provided.
        """
        if importance is None:
            importance = _auto_importance(user_msg + " " + assistant_msg)

        uid = await self.store(
            content=f"User: {user_msg}",
            importance=importance,
            memory_type="episode",
            mission_id=mission_id,
        )
        aid = await self.store(
            content=f"Assistant: {assistant_msg}",
            importance=importance,
            memory_type="episode",
            mission_id=mission_id,
        )
        return uid, aid

    async def build_context_prompt(self, query: str, top_k: int = 5) -> str:
        """
        Build a memory context block to prepend to an LLM prompt.
        Retrieves relevant memories and formats them.
        """
        memories = await self.retrieve(query, top_k=top_k)
        if not memories:
            return ""

        lines = ["[Relevant memories]"]
        for m in memories:
            ts = m.get("created_at", 0)
            age = _human_age(ts)
            lines.append(f"• [{m.get('source','?')} | {age} | imp={m.get('importance',0):.1f}] {m.get('content','')}")
        return "\n".join(lines) + "\n"


# ── Importance estimation ──────────────────────────────────────────────────────

_IMPORTANCE_KEYWORDS = {
    "error", "erreur", "bug", "fix", "fixed", "résolu", "learned", "appris",
    "important", "critical", "critique", "remember", "souviens", "decision",
    "décision", "mission", "deployed", "déployé", "architecture", "strategy",
    "stratégie", "fail", "échec", "success", "succès", "breaking",
}

def _auto_importance(text: str) -> float:
    """
    Heuristic importance score 0.0–1.0 based on keyword presence and length.
    Tune to your domain.
    """
    words = set(text.lower().split())
    hits = words & _IMPORTANCE_KEYWORDS
    keyword_score = min(len(hits) / 3, 1.0)   # saturates at 3 keywords
    length_score  = min(len(text) / 500, 1.0)  # longer = probably richer
    return round(0.4 + 0.4 * keyword_score + 0.2 * length_score, 2)


def _human_age(ts: float) -> str:
    diff = time.time() - ts
    if diff < 120:
        return "just now"
    if diff < 3600:
        return f"{int(diff/60)}m ago"
    if diff < 86400:
        return f"{int(diff/3600)}h ago"
    return f"{int(diff/86400)}d ago"


# ── CLI smoke test ─────────────────────────────────────────────────────────────

async def _smoke_test():
    ms = MemorySystem(session_id="smoke-test")
    print("=== JarvisMax Memory System — Smoke Test ===\n")

    # Working memory
    await ms._wm.set("last_topic", "AGI memory architecture")
    val = await ms._wm.get("last_topic")
    print(f"[Working] Retrieved: {val}")

    # Episode store
    mid = await ms.store(
        "We decided to use Qdrant for semantic search in JarvisMax.",
        importance=0.8,
        memory_type="episode",
        mission_id="smoke-test",
    )
    print(f"[Episode] Stored: {mid}")

    # Semantic store
    sid = await ms.store(
        "JarvisMax uses a 3-level memory: working → Redis, episodes → Qdrant, semantic → Qdrant.",
        importance=0.95,
        memory_type="semantic",
    )
    print(f"[Semantic] Stored: {sid}")

    # Retrieve
    results = await ms.retrieve("Qdrant semantic search", top_k=3)
    print(f"\n[Retrieve] Top {len(results)} results:")
    for r in results:
        print(f"  [{r['source']} | score={r['score']:.3f}] {r['content'][:80]}")

    # Summarise
    summary = await ms.summarize_episode("smoke-test")
    print(f"\n[Summary]\n{summary}")

    # Forget (dry: nothing old enough yet)
    n = await ms.forget(older_than_days=30, importance_below=0.3)
    print(f"\n[Forget] Deleted {n} stale memories")

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_smoke_test())


# ── UnifiedMemory : compatibility facade ──────────────────────────────────────
# Exposes recall(query, top_k) and store(content, memory_type, metadata)
# with sensible defaults, so meta_orchestrator.py hooks stay concise.

class UnifiedMemory:
    """
    Thin façade over MemorySystem that provides a simpler two-method API:

        await um.recall(query, top_k=3)    → list[dict]
        await um.store(content, memory_type, metadata)  → str

    Both methods are fail-open — any exception inside MemorySystem is
    propagated to the caller (who is expected to catch it).
    """

    def __init__(self, session_id: str | None = None):
        import uuid as _uuid
        self._ms = MemorySystem(session_id=session_id or str(_uuid.uuid4()))

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        memory_types: list | None = None,
        min_importance: float = 0.3,
    ) -> list[dict]:
        """Retrieve relevant memories. Returns list of dicts with 'content' key."""
        return await self._ms.retrieve(
            query=query,
            top_k=top_k,
            memory_types=memory_types,
            min_importance=min_importance,
        )

    async def store(
        self,
        content: str,
        memory_type: str = "episode",
        metadata: dict | None = None,
        importance: float = 0.7,
    ) -> str:
        """Store a memory. Returns memory_id."""
        return await self._ms.store(
            content=content,
            importance=importance,
            memory_type=memory_type,  # type: ignore[arg-type]
            metadata=metadata,
        )

