"""
JARVIS MAX — VectorStore (pgvector backend)
Stockage et recherche de similarité vectorielle via PostgreSQL + pgvector.

Usage :
    vs = VectorStore(settings)
    await vs.ensure_table()
    await vs.store_embedding(content="...", embedding=[...], metadata={})
    results = await vs.search_similar(embedding=[...], top_k=5)

Fallback :
    Si pgvector/asyncpg est indisponible, is_available() retourne False
    et toutes les opérations sont no-ops silencieuses.
"""
from __future__ import annotations

import uuid

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger(__name__)

TARGET_DIM = 768

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS embeddings (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT        NOT NULL,
    embedding   vector({dim}),
    metadata    JSONB       DEFAULT '{{}}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
""".format(dim=TARGET_DIM)

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS embeddings_ivfflat_idx
ON embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
"""


class VectorStore:
    """pgvector-backed embedding store with graceful fallback."""

    def __init__(self, settings):
        self.s = settings
        self._pool = None
        self._available: bool | None = None   # None = not yet tested

    # ── Availability ──────────────────────────────────────────

    def is_available(self) -> bool:
        """Returns True only after a successful ensure_table() call."""
        return self._available is True

    # ── Schema bootstrap ──────────────────────────────────────

    async def ensure_table(self) -> bool:
        """
        Creates the embeddings table + IVFFlat index if they don't exist.
        Returns True on success, False if pgvector/asyncpg is unavailable.
        Sets self._available accordingly.
        """
        try:
            pool = await self._get_pool()
            if pool is None:
                self._available = False
                return False

            async with pool.acquire() as conn:
                await self._register_vector(conn)
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                await conn.execute(_CREATE_TABLE)
                try:
                    await conn.execute(_CREATE_INDEX)
                except Exception:
                    pass   # index may require data; ignore error

            self._available = True
            log.info("vector_store_ready", dim=TARGET_DIM)
            return True

        except Exception as e:
            self._available = False
            log.warning("vector_store_unavailable", err=str(e)[:120])
            return False

    # ── Write ─────────────────────────────────────────────────

    async def store_embedding(
        self,
        content:   str,
        embedding: list[float],
        metadata:  dict | None = None,
        doc_id:    str | None  = None,
    ) -> str | None:
        """
        Inserts a document + its embedding vector.
        Returns the UUID string on success, None on failure.
        """
        if not self.is_available():
            return None
        try:
            import json
            vec   = self._pad_or_truncate(embedding, TARGET_DIM)
            row_id = doc_id or str(uuid.uuid4())
            pool   = await self._get_pool()
            async with pool.acquire() as conn:
                await self._register_vector(conn)
                await conn.execute(
                    """
                    INSERT INTO embeddings (id, content, embedding, metadata)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE
                        SET content   = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            metadata  = EXCLUDED.metadata;
                    """,
                    uuid.UUID(row_id),
                    content,
                    vec,
                    json.dumps(metadata or {}),
                )
            return row_id
        except Exception as e:
            log.warning("vector_store_store_failed", err=str(e)[:120])
            return None

    # ── Read ──────────────────────────────────────────────────

    async def search_similar(
        self,
        embedding:  list[float],
        top_k:      int   = 5,
        min_score:  float = 0.0,
        filter_meta: dict | None = None,
    ) -> list[dict]:
        """
        Returns top_k nearest neighbours sorted by cosine similarity desc.
        Each result: {"id", "content", "score", "metadata"}.
        """
        if not self.is_available():
            return []
        try:
            import json
            vec  = self._pad_or_truncate(embedding, TARGET_DIM)
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await self._register_vector(conn)
                # Cosine distance: 1 - similarity; lower is closer
                rows = await conn.fetch(
                    """
                    SELECT id::text,
                           content,
                           metadata,
                           1 - (embedding <=> $1::vector) AS score
                    FROM   embeddings
                    ORDER  BY embedding <=> $1::vector
                    LIMIT  $2;
                    """,
                    vec,
                    top_k,
                )
            results = []
            for r in rows:
                score = float(r["score"])
                if score < min_score:
                    continue
                results.append({
                    "id":       r["id"],
                    "content":  r["content"],
                    "score":    score,
                    "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str)
                                else (r["metadata"] or {}),
                })
            return results
        except Exception as e:
            log.warning("vector_store_search_failed", err=str(e)[:120])
            return []

    async def delete_by_metadata(self, filter_meta: dict) -> int:
        """Deletes rows whose metadata @> filter_meta. Returns deleted count."""
        if not self.is_available() or not filter_meta:
            return 0
        try:
            import json
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM embeddings WHERE metadata @> $1::jsonb;",
                    json.dumps(filter_meta),
                )
            # result is e.g. "DELETE 3"
            return int(result.split()[-1])
        except Exception as e:
            log.warning("vector_store_delete_failed", err=str(e)[:120])
            return 0

    async def count(self) -> int:
        """Returns total number of stored embeddings."""
        if not self.is_available():
            return 0
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT COUNT(*) AS n FROM embeddings;")
            return int(row["n"])
        except Exception as e:
            log.warning("vector_store_count_failed", err=str(e)[:80])
            return 0

    # ── Internal helpers ──────────────────────────────────────

    async def _get_pool(self):
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
            dsn = getattr(self.s, "database_url", None) or getattr(self.s, "pg_dsn", None)
            if not dsn:
                return None
            self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
            return self._pool
        except Exception as e:
            log.warning("vector_store_pool_failed", err=str(e)[:80])
            return None

    @staticmethod
    async def _register_vector(conn) -> None:
        """Optionally registers pgvector codec; silently skipped if unavailable."""
        try:
            from pgvector.asyncpg import register_vector
            await register_vector(conn)
        except Exception:
            pass   # pgvector Python package not installed — raw list<float> still works

    @staticmethod
    def _pad_or_truncate(vec: list[float], target: int) -> list[float]:
        if len(vec) >= target:
            return vec[:target]
        return vec + [0.0] * (target - len(vec))

    async def close(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                _silent_log.debug("suppressed_exception", src='vector_store.py')
            self._pool = None
