"""
JARVIS MAX — EmbeddingProvider
Génération d'embeddings via nomic-embed-text (768 dimensions).

Cascade :
    1. Ollama  nomic-embed-text       (768 dims native)
    2. Local   all-MiniLM-L6-v2      (384 dims → paddé à 768)

Usage :
    ep = EmbeddingProvider(settings)
    vec   = await ep.embed("Du texte ici")           # list[float] taille 768
    vecs  = await ep.embed_batch(["a", "b", "c"])    # list[list[float]]
    chunks = ep.chunk_text(code, strategy="ast_aware")
"""
from __future__ import annotations

import asyncio
import re
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

TARGET_DIM = 768
ChunkStrategy = Literal["fixed_size", "sentence", "ast_aware"]


class EmbeddingProvider:
    """
    Multi-provider embedding facade.
    Always returns TARGET_DIM (768) dimensional vectors via nomic-embed-text.
    """

    def __init__(self, settings, provider: str = "auto"):
        self.s = settings
        self._provider = provider   # "auto" | "openai" | "ollama" | "local"
        self._local_model = None    # lazy sentence-transformers model

    # ── Public API ────────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns 768-dim vector."""
        if not text or not text.strip():
            return [0.0] * TARGET_DIM
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Returns list of 768-dim vectors."""
        if not texts:
            return []

        if self._provider in ("auto", "openai"):
            try:
                vecs = await self._embed_openai(texts)
                return [self._pad_or_truncate(v, TARGET_DIM) for v in vecs]
            except Exception as e:
                if self._provider == "openai":
                    raise
                log.debug("embed_openai_failed", err=str(e)[:80])

        if self._provider in ("auto", "ollama"):
            try:
                vecs = await self._embed_ollama(texts)
                return [self._pad_or_truncate(v, TARGET_DIM) for v in vecs]
            except Exception as e:
                if self._provider == "ollama":
                    raise
                log.debug("embed_ollama_failed", err=str(e)[:80])

        # Local fallback (always available after first model load)
        vecs = await asyncio.get_running_loop().run_in_executor(
            None, self._embed_local_sync, texts
        )
        return [self._pad_or_truncate(v, TARGET_DIM) for v in vecs]

    # ── Chunking ──────────────────────────────────────────────

    def chunk_text(
        self,
        text: str,
        strategy: ChunkStrategy = "fixed_size",
        chunk_size: int = 500,
        overlap: int    = 50,
    ) -> list[str]:
        """
        Split text into chunks suitable for embedding.

        Strategies:
            fixed_size  — character windows with word-boundary snapping
            sentence    — split on sentence boundaries
            ast_aware   — Python AST (FunctionDef/ClassDef as units)
        """
        if not text or not text.strip():
            return []

        if strategy == "fixed_size":
            return self._chunk_fixed(text, chunk_size, overlap)
        elif strategy == "sentence":
            return self._chunk_sentence(text, chunk_size)
        elif strategy == "ast_aware":
            return self._chunk_ast(text, chunk_size, overlap)
        else:
            return self._chunk_fixed(text, chunk_size, overlap)

    # ── Provider implementations ──────────────────────────────

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        import openai
        api_key = getattr(self.s, "openai_api_key", None)
        if not api_key:
            raise RuntimeError("No OpenAI API key")
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in response.data]

    async def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        import httpx
        host = getattr(self.s, "ollama_host", "http://localhost:11434")
        results = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for text in texts:
                resp = await client.post(
                    f"{host}/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": text},
                )
                resp.raise_for_status()
                results.append(resp.json()["embedding"])
        return results

    def _embed_local_sync(self, texts: list[str]) -> list[list[float]]:
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = self._local_model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]

    # ── Chunking implementations ──────────────────────────────

    @staticmethod
    def _chunk_fixed(text: str, size: int, overlap: int) -> list[str]:
        chunks = []
        start  = 0
        n      = len(text)
        while start < n:
            end = min(start + size, n)
            # Snap to word boundary (look back up to 20 chars)
            if end < n:
                snap = text.rfind(" ", max(start, end - 20), end)
                if snap > start:
                    end = snap
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= n:
                break
            # Guarantee forward progress: advance by at least 1 char
            next_start = end - overlap
            start = max(start + 1, next_start)
        return chunks

    @staticmethod
    def _chunk_sentence(text: str, max_size: int) -> list[str]:
        # Split on '. ', '! ', '? ' boundaries
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        chunks = []
        current = ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if len(current) + len(sent) + 1 > max_size and current:
                chunks.append(current.strip())
                current = sent
            else:
                current = (current + " " + sent).strip() if current else sent
        if current.strip():
            chunks.append(current.strip())
        return chunks

    @staticmethod
    def _chunk_ast(text: str, size: int, overlap: int) -> list[str]:
        try:
            import ast as ast_mod
            tree   = ast_mod.parse(text)
            lines  = text.splitlines(keepends=True)
            chunks = []
            for node in ast_mod.walk(tree):
                if isinstance(node, (ast_mod.FunctionDef, ast_mod.AsyncFunctionDef,
                                     ast_mod.ClassDef)):
                    start = node.lineno - 1
                    end   = getattr(node, "end_lineno", start + 1)
                    block = "".join(lines[start:end]).strip()
                    if block:
                        chunks.append(block)
            if not chunks:
                raise ValueError("no top-level nodes")
            return chunks
        except Exception:
            # Fallback to fixed-size for non-Python or parse errors
            return EmbeddingProvider._chunk_fixed(text, size, overlap)

    # ── Utility ───────────────────────────────────────────────

    @staticmethod
    def _pad_or_truncate(vec: list[float], target: int) -> list[float]:
        if len(vec) >= target:
            return vec[:target]
        return vec + [0.0] * (target - len(vec))
