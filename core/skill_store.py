"""
core/skill_store.py — Voyager-pattern Skill Store for JarvisMax
================================================================
Stores and retrieves successful mission patterns as reusable skills.

Pattern inspired by: Voyager (Wang et al., 2023) — arxiv:2305.16291
Memory scoring inspired by: Generative Agents (Park et al., 2023) — arxiv:2304.03442

Design:
  - Skills = successful mission plans with confidence > 0.7
  - Stored in Qdrant collection 'jarvis_skills' with vector embeddings
  - Retrieved by semantic similarity at mission planning time
  - Importance score = success_count × avg_confidence (higher = more valuable)
  - Fail-open: if Qdrant unavailable, retrieve() returns [] silently

Usage:
    store = get_skill_store()
    
    # After a successful mission:
    await store.store(mission_id, goal, plan, confidence, mission_type)
    
    # Before planning a new mission:
    similar = await store.retrieve(goal, top_k=3)
    # → injects into planner context
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("jarvis.skill_store")

_QDRANT_URL  = os.environ.get("QDRANT_URL", "http://qdrant:6333")
_QDRANT_KEY  = os.environ.get("QDRANT_API_KEY", "")
_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
_COLLECTION  = "jarvis_skills"
_VECTOR_SIZE = 768   # nomic-embed-text standard dimension
_MIN_CONFIDENCE_TO_STORE = float(os.environ.get("SKILL_MIN_CONFIDENCE", "0.70"))
_MAX_SKILLS  = int(os.environ.get("SKILL_MAX_STORE", "500"))


# ── Data model ────────────────────────────────────────────────

@dataclass
class Skill:
    skill_id:      str
    name:          str           # short label derived from goal
    goal:          str           # original goal text
    mission_type:  str
    plan_summary:  str           # JSON-serialized plan steps
    confidence:    float
    success_count: int   = 1
    use_count:     int   = 0
    avg_confidence: float = 0.0
    created_at:    float = field(default_factory=time.time)
    last_used:     float = field(default_factory=time.time)
    tags:          list  = field(default_factory=list)

    def importance_score(self) -> float:
        """Higher = more valuable. Mirrors Generative Agents importance scoring."""
        recency  = 1.0 / max(1.0, (time.time() - self.last_used) / 86400)  # day-decay
        quality  = self.avg_confidence or self.confidence
        usage    = min(1.0, self.success_count / 10.0)
        return (quality * 0.5 + recency * 0.3 + usage * 0.2)

    def to_payload(self) -> dict:
        d = asdict(self)
        d["importance"] = self.importance_score()
        return d


# ── Embedding helpers ─────────────────────────────────────────

def _hash_embed(text: str, size: int = _VECTOR_SIZE) -> list[float]:
    """Deterministic fallback embedding from SHA-256 hash. Never fails."""
    raw = hashlib.sha256(text.encode()).digest()
    # Repeat bytes to fill size
    repeated = (raw * ((size // len(raw)) + 1))[:size]
    vec = [(b / 127.5) - 1.0 for b in repeated]
    norm = (sum(v * v for v in vec) ** 0.5) or 1.0
    return [v / norm for v in vec]


async def _ollama_embed(text: str) -> list[float]:
    """Async Ollama embedding. Returns hash fallback on any failure."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{_OLLAMA_HOST}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text}
            )
            if r.status_code == 200:
                emb = r.json().get("embedding", [])
                if len(emb) == _VECTOR_SIZE:
                    return emb
    except Exception as _e:
        log.debug("ollama_embed_failed", err=str(_e)[:80])
    return _hash_embed(text)


# ── SkillStore ────────────────────────────────────────────────

class SkillStore:
    """
    Qdrant-backed skill library. All methods fail-open.
    Thread-safe via asyncio; singleton via get_skill_store().
    """

    def __init__(self) -> None:
        self._client: Any | None = None
        self._ready = False
        self._lock = asyncio.Lock()

    async def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams, HnswConfigDiff
            kw: dict = {"url": _QDRANT_URL, "timeout": 10}
            if _QDRANT_KEY:
                kw["api_key"] = _QDRANT_KEY
            c = QdrantClient(**kw)
            # Ensure collection exists
            existing = {col.name for col in c.get_collections().collections}
            if _COLLECTION not in existing:
                c.create_collection(
                    collection_name=_COLLECTION,
                    vectors_config=VectorParams(size=_VECTOR_SIZE, distance=Distance.COSINE),
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=200),
                )
                log.info("skill_collection_created", collection=_COLLECTION, size=_VECTOR_SIZE)
            self._client = c
            self._ready = True
            log.info("skill_store_ready", collection=_COLLECTION)
        except Exception as e:
            log.warning("skill_store_init_failed", err=str(e)[:120])
        return self._client

    # ── Write ─────────────────────────────────────────────────

    async def store(
        self,
        mission_id: str,
        goal: str,
        plan: dict | list | str,
        confidence: float,
        mission_type: str = "general",
        tags: list | None = None,
    ) -> bool:
        """
        Store a successful mission as a reusable skill.
        Only stores if confidence >= _MIN_CONFIDENCE_TO_STORE.
        Returns True if stored, False otherwise.
        """
        if confidence < _MIN_CONFIDENCE_TO_STORE:
            log.debug("skill_store_skip", reason="low_confidence", confidence=confidence)
            return False

        try:
            async with self._lock:
                client = await self._get_client()
                if client is None:
                    return False

                plan_str = plan if isinstance(plan, str) else json.dumps(plan, ensure_ascii=False)
                name = goal[:60].strip().replace("\n", " ")
                skill_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mission_type}:{goal[:200]}"))

                # Check if skill already exists → update stats instead of duplicate
                try:
                    existing = client.retrieve(collection_name=_COLLECTION, ids=[skill_id])
                    if existing:
                        old = existing[0].payload or {}
                        sc = old.get("success_count", 1) + 1
                        uc = old.get("use_count", 0)
                        prev_avg = old.get("avg_confidence", confidence)
                        new_avg = (prev_avg * (sc - 1) + confidence) / sc
                        client.set_payload(
                            collection_name=_COLLECTION,
                            payload={
                                "success_count": sc,
                                "use_count": uc,
                                "avg_confidence": round(new_avg, 4),
                                "last_used": time.time(),
                                "importance": min(1.0, new_avg * 0.5 + min(1.0, sc / 10) * 0.5),
                            },
                            points=[skill_id],
                        )
                        log.info("skill_updated", skill_id=skill_id, success_count=sc)
                        return True
                except Exception:
                    pass  # New skill — proceed to insert

                embedding = await _ollama_embed(f"{goal}\n{plan_str[:300]}")
                skill = Skill(
                    skill_id=skill_id,
                    name=name,
                    goal=goal[:500],
                    mission_type=mission_type,
                    plan_summary=plan_str[:1000],
                    confidence=confidence,
                    avg_confidence=confidence,
                    tags=tags or [],
                )
                from qdrant_client.models import PointStruct
                client.upsert(
                    collection_name=_COLLECTION,
                    points=[PointStruct(
                        id=skill_id,
                        vector=embedding,
                        payload=skill.to_payload(),
                    )],
                )
                log.info("skill_stored", skill_id=skill_id, name=name, confidence=confidence)
                return True

        except Exception as e:
            log.warning("skill_store_write_failed", err=str(e)[:120])
            return False

    # ── Read ──────────────────────────────────────────────────

    async def retrieve(
        self,
        goal: str,
        top_k: int = 3,
        min_score: float = 0.70,
        mission_type: str | None = None,
    ) -> list[dict]:
        """
        Retrieve top-k similar skills for a given goal.
        Returns [] on any error (fail-open).
        """
        try:
            client = await self._get_client()
            if client is None:
                return []

            embedding = await _ollama_embed(goal)
            filter_kw: dict = {}
            if mission_type:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                filter_kw["query_filter"] = Filter(
                    must=[FieldCondition(key="mission_type", match=MatchValue(value=mission_type))]
                )

            # qdrant-client v1.7+: use query_points (search was removed in v1.13+)
            from qdrant_client.models import QueryRequest
            qp_kwargs: dict = {
                "collection_name": _COLLECTION,
                "query": embedding,
                "limit": top_k,
                "score_threshold": min_score,
                "with_payload": True,
            }
            if filter_kw.get("query_filter"):
                qp_kwargs["query_filter"] = filter_kw["query_filter"]

            response = client.query_points(**qp_kwargs)
            results = response.points if hasattr(response, "points") else response

            skills = []
            for hit in results:
                p = hit.payload or {}
                p["_score"] = round(hit.score, 4)
                # Update use_count
                try:
                    client.set_payload(
                        collection_name=_COLLECTION,
                        payload={
                            "use_count": p.get("use_count", 0) + 1,
                            "last_used": time.time(),
                        },
                        points=[hit.id],
                    )
                except Exception:
                    _silent_log.debug("suppressed_exception", src='skill_store.py')
                skills.append(p)

            if skills:
                log.info("skills_retrieved", goal_len=len(goal), count=len(skills),
                         top_score=skills[0]["_score"])
            return skills

        except Exception as e:
            log.warning("skill_retrieve_failed", err=str(e)[:120])
            return []

    # ── Utilities ─────────────────────────────────────────────

    async def stats(self) -> dict:
        """Return skill store statistics. Fail-open."""
        try:
            client = await self._get_client()
            if client is None:
                return {"available": False}
            info = client.get_collection(_COLLECTION)
            return {
                "available": True,
                "total_skills": info.points_count,
                "collection": _COLLECTION,
                "vector_size": _VECTOR_SIZE,
            }
        except Exception as e:
            return {"available": False, "error": str(e)[:80]}

    async def top_skills(self, limit: int = 10) -> list[dict]:
        """Return skills sorted by importance score. Fail-open."""
        try:
            client = await self._get_client()
            if client is None:
                return []
            from qdrant_client.models import ScrollRequest
            results, _ = client.scroll(
                collection_name=_COLLECTION,
                limit=min(limit * 5, 200),
                with_payload=True,
            )
            skills = [r.payload for r in results if r.payload]
            skills.sort(key=lambda x: x.get("importance", 0), reverse=True)
            return skills[:limit]
        except Exception as e:
            log.warning("skill_top_failed", err=str(e)[:80])
            return []


# ── Singleton ─────────────────────────────────────────────────

_instance: SkillStore | None = None

def get_skill_store() -> SkillStore:
    global _instance
    if _instance is None:
        _instance = SkillStore()
    return _instance


# ── Context builder (for prompt injection) ───────────────────

def format_skills_for_prompt(skills: list[dict]) -> str:
    """
    Format retrieved skills as a prompt-injectable context block.
    Returns empty string if no skills.
    """
    if not skills:
        return ""
    lines = ["## Missions similaires réussies (contexte)\n"]
    for i, s in enumerate(skills, 1):
        score = s.get("_score", 0)
        name = s.get("name", "?")[:60]
        plan = s.get("plan_summary", "")[:300]
        conf = s.get("avg_confidence", s.get("confidence", 0))
        sc   = s.get("success_count", 1)
        lines.append(
            f"### Skill {i} (similarité {score:.0%}, confiance {conf:.0%}, {sc}× réussi)\n"
            f"**Objectif:** {name}\n"
            f"**Plan:** {plan}\n"
        )
    return "\n".join(lines)
