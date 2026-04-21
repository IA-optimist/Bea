"""
JARVIS MAX — RAG Pipeline
index_document → chunk → embed → store in pgvector (SQLite in-memory fallback)
query          → embed question → search → rerank → RagResult

Mtime tracking: SQLite table `rag_index_tracker` records (path, mtime, doc_id)
so unchanged files are skipped on re-index.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_CHUNK_STRATEGY_MAP = {
    ".py":   "ast_aware",
    ".js":   "ast_aware",
    ".ts":   "ast_aware",
    ".md":   "sentence",
    ".rst":  "sentence",
    ".txt":  "sentence",
}
_DEFAULT_CHUNK_STRATEGY = "fixed_size"
_DEFAULT_CHUNK_SIZE      = 800   # chars


# ── Result type ───────────────────────────────────────────────

@dataclass
class RagResult:
    answer_context: str              # concatenated relevant chunks
    sources:        list[str]        = field(default_factory=list)
    scores:         list[float]      = field(default_factory=list)
    chunks:         list[str]        = field(default_factory=list)
    total_found:    int              = 0

    @property
    def ok(self) -> bool:
        return bool(self.chunks)

    def to_dict(self) -> dict:
        return {
            "answer_context": self.answer_context[:500] + "..." if len(self.answer_context) > 500 else self.answer_context,
            "sources":        self.sources,
            "scores":         [round(s, 4) for s in self.scores],
            "total_found":    self.total_found,
        }


# ── Mtime tracker (SQLite) ────────────────────────────────────

class _MtimeTracker:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._ensure()

    def _ensure(self) -> None:
        con = sqlite3.connect(self._path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS rag_index_tracker (
                path    TEXT PRIMARY KEY,
                mtime   REAL,
                doc_id  TEXT,
                indexed_at REAL
            );
        """)
        con.commit()
        con.close()

    def is_stale(self, path: str) -> bool:
        """Returns True if file is new or mtime changed since last index."""
        try:
            mtime = os.stat(path).st_mtime
        except FileNotFoundError:
            return False
        con = sqlite3.connect(self._path)
        row = con.execute(
            "SELECT mtime FROM rag_index_tracker WHERE path=?", (path,)
        ).fetchone()
        con.close()
        if row is None:
            return True
        return float(row[0]) != mtime

    def record(self, path: str, doc_id: str) -> None:
        try:
            mtime = os.stat(path).st_mtime
        except FileNotFoundError:
            mtime = 0.0
        con = sqlite3.connect(self._path)
        con.execute("""
            INSERT INTO rag_index_tracker (path, mtime, doc_id, indexed_at)
            VALUES (?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                mtime=excluded.mtime,
                doc_id=excluded.doc_id,
                indexed_at=excluded.indexed_at;
        """, (path, mtime, doc_id, time.time()))
        con.commit()
        con.close()

    def stats(self) -> dict:
        con = sqlite3.connect(self._path)
        row = con.execute("""
            SELECT COUNT(*), MAX(indexed_at) FROM rag_index_tracker
        """).fetchone()
        con.close()
        return {
            "indexed_files": row[0] if row else 0,
            "last_indexed":  row[1] if row else None,
        }


# ── In-memory fallback store ──────────────────────────────────

class _MemoryStore:
    """Simple in-process vector store using dot-product similarity."""

    def __init__(self) -> None:
        self._docs: list[dict] = []

    async def ensure_table(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    async def store_embedding(
        self,
        content:   str,
        embedding: list[float],
        metadata:  dict,
    ) -> str:
        import uuid
        doc_id = str(uuid.uuid4())
        self._docs.append({
            "id":        doc_id,
            "content":   content,
            "embedding": embedding,
            "metadata":  metadata,
        })
        return doc_id

    async def search_similar(
        self,
        embedding:   list[float],
        top_k:       int   = 5,
        min_score:   float = 0.0,
        filter_meta: dict | None = None,
    ) -> list[dict]:
        if not self._docs:
            return []
        scored = []
        q = embedding
        q_norm = sum(x*x for x in q) ** 0.5 or 1.0
        for doc in self._docs:
            d = doc["embedding"]
            d_norm = sum(x*x for x in d) ** 0.5 or 1.0
            dot    = sum(a*b for a, b in zip(q, d))
            score  = dot / (q_norm * d_norm)
            if score >= min_score:
                scored.append({**doc, "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def count(self) -> int:
        return len(self._docs)


# ── RagPipeline ───────────────────────────────────────────────

class RagPipeline:
    """
    Full RAG pipeline: ingest → chunk → embed → store → query.
    Uses pgvector if available, falls back to in-process memory store.
    """

    def __init__(self, settings=None) -> None:
        self.s        = settings
        self._store   = None   # VectorStore | _MemoryStore
        self._embed   = None   # EmbeddingProvider
        self._tracker = None   # _MtimeTracker

    # ── Bootstrap ─────────────────────────────────────────────

    async def _get_store(self):
        if self._store is not None:
            return self._store
        try:
            from memory.vector_store import VectorStore
            s = self.s or self._settings()
            vs = VectorStore(s)
            ok = await vs.ensure_table()
            if ok:
                self._store = vs
                log.debug("rag_store_pgvector")
                return self._store
        except Exception as e:
            log.debug("rag_pgvector_unavailable", err=str(e)[:60])
        self._store = _MemoryStore()
        log.debug("rag_store_memory_fallback")
        return self._store

    def _get_embed(self):
        if self._embed is not None:
            return self._embed
        try:
            from memory.embeddings import EmbeddingProvider
            s = self.s or self._settings()
            self._embed = EmbeddingProvider(s)
        except Exception:
            self._embed = _NullEmbedder()
        return self._embed

    def _get_tracker(self) -> _MtimeTracker:
        if self._tracker is None:
            db_path = os.path.join(tempfile.gettempdir(), "jarvis_rag_tracker.db")
            self._tracker = _MtimeTracker(db_path)
        return self._tracker

    @staticmethod
    def _settings():
        try:
            from config.settings import get_settings
            return get_settings()
        except Exception:
            return None

    # ── Chunking ──────────────────────────────────────────────

    def _chunk(self, doc) -> list[str]:
        ext      = Path(doc.source).suffix.lower()
        strategy = _CHUNK_STRATEGY_MAP.get(ext, _DEFAULT_CHUNK_STRATEGY)
        embed    = self._get_embed()
        try:
            chunks = embed.chunk_text(doc.content, strategy=strategy, chunk_size=_DEFAULT_CHUNK_SIZE)
        except Exception:
            # Dumb fallback: split on newlines
            chunks = [
                doc.content[i:i+_DEFAULT_CHUNK_SIZE]
                for i in range(0, len(doc.content), _DEFAULT_CHUNK_SIZE)
            ]
        return [c for c in chunks if c.strip()]

    # ── Public: index_document ────────────────────────────────

    async def index_document(
        self,
        path_or_text: str | Path,
        metadata:     dict | None = None,
        force:        bool        = False,
    ) -> dict:
        """
        Ingest, chunk, embed, and store a file or text string.
        Skips unchanged files unless force=True.
        Returns summary dict.
        """
        from core.rag.ingestion import ingest_file, ingest_text

        path_str = str(path_or_text)
        tracker  = self._get_tracker()

        # Skip unchanged files
        if not force and os.path.isfile(path_str) and not tracker.is_stale(path_str):
            log.debug("rag_skip_unchanged", path=path_str)
            return {"skipped": True, "path": path_str}

        # Ingest
        if os.path.isfile(path_str):
            doc = await ingest_file(path_str)
        else:
            doc = await ingest_text(path_str, metadata=metadata)

        if metadata:
            doc.metadata.update(metadata)

        # Chunk
        chunks = self._chunk(doc)
        doc.chunks = chunks

        if not chunks:
            return {"skipped": True, "reason": "empty_content", "path": path_str}

        # Embed + store
        store  = await self._get_store()
        embed  = self._get_embed()
        stored = 0

        for i, chunk in enumerate(chunks):
            try:
                vec = await embed.embed(chunk)
                chunk_meta = {
                    **doc.metadata,
                    "doc_id":   doc.id,
                    "chunk_idx": i,
                    "source":    doc.source,
                }
                await store.store_embedding(
                    content   = chunk,
                    embedding = vec,
                    metadata  = chunk_meta,
                )
                stored += 1
            except Exception as e:
                log.warning("rag_chunk_store_failed", chunk=i, err=str(e)[:80])

        # Track mtime
        if os.path.isfile(path_str):
            tracker.record(path_str, doc.id)

        log.info("rag_indexed", source=doc.source, chunks=stored)
        return {
            "doc_id":   doc.id,
            "source":   doc.source,
            "chunks":   stored,
            "words":    doc.word_count,
            "skipped":  False,
        }

    # ── Public: query ─────────────────────────────────────────

    async def query(
        self,
        question: str,
        top_k:    int   = 5,
        min_score: float = 0.3,
    ) -> RagResult:
        """
        Embed question, search vector store, return RagResult.
        """
        store = await self._get_store()
        embed = self._get_embed()

        try:
            q_vec = await embed.embed(question)
        except Exception as e:
            log.warning("rag_query_embed_failed", err=str(e)[:80])
            return RagResult(answer_context="", sources=[], scores=[])

        try:
            results = await store.search_similar(
                embedding  = q_vec,
                top_k      = top_k,
                min_score  = min_score,
            )
        except Exception as e:
            log.warning("rag_query_search_failed", err=str(e)[:80])
            return RagResult(answer_context="", sources=[], scores=[])

        if not results:
            return RagResult(answer_context="", sources=[], scores=[], total_found=0)

        chunks  = [r["content"] for r in results]
        scores  = [r.get("score", 0.0) for r in results]
        sources = []
        for r in results:
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                import json
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            src = meta.get("source", r.get("id", "unknown"))
            if src not in sources:
                sources.append(src)

        context = "\n\n---\n\n".join(chunks)
        return RagResult(
            answer_context = context,
            sources        = sources,
            scores         = scores,
            chunks         = chunks,
            total_found    = len(results),
        )

    # ── Public: index_codebase ────────────────────────────────

    async def index_codebase(
        self,
        root_dir:   str | Path,
        extensions: list[str] | None = None,
        max_files:  int = 500,
    ) -> dict:
        """
        Walk root_dir and index all matching files.
        Returns summary with total/skipped/failed counts.
        """
        from core.rag.ingestion import _SUPPORTED
        exts    = set(extensions or list(_SUPPORTED.keys()))
        root    = Path(root_dir)
        total   = skipped = failed = 0
        results = []

        for fp in root.rglob("*"):
            if total >= max_files:
                break
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in exts:
                continue
            # Skip hidden dirs / __pycache__ / .git
            if any(p.startswith(".") or p == "__pycache__" for p in fp.parts):
                continue

            total += 1
            try:
                r = await self.index_document(str(fp))
                if r.get("skipped"):
                    skipped += 1
                results.append(r)
            except Exception as e:
                failed += 1
                log.warning("rag_codebase_file_failed", path=str(fp), err=str(e)[:80])

        log.info("rag_codebase_indexed", root=str(root), total=total, skipped=skipped, failed=failed)
        return {"total": total, "skipped": skipped, "failed": failed, "root": str(root)}

    # ── Status ────────────────────────────────────────────────

    async def status(self) -> dict:
        tracker = self._get_tracker()
        store   = await self._get_store()
        s       = tracker.stats()
        try:
            vec_count = await store.count()
        except Exception:
            vec_count = 0
        return {
            **s,
            "vector_count": vec_count,
            "store_backend": "pgvector" if hasattr(store, "_pool") else "memory",
        }


# ── Null embedder (no deps) ───────────────────────────────────

class _NullEmbedder:
    """Returns zero vectors when no embedding provider is available."""

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 1536

    def chunk_text(self, text: str, strategy: str = "fixed_size", chunk_size: int = 800) -> list[str]:
        return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]


# ── Singleton ─────────────────────────────────────────────────

_pipeline: RagPipeline | None = None


def get_rag_pipeline(settings=None) -> RagPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RagPipeline(settings)
    return _pipeline

# Alias for backward compatibility (some consumers use uppercase RAG)
RAGPipeline = RagPipeline
