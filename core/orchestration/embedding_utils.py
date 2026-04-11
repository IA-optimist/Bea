"""
Lightweight Embedding Utilities for Causal Module
==================================================

Provides 384-dimensional embeddings for causal graph semantic search.

ARCHITECTURE:
- Fallback chain: OpenAI → memory.embeddings.EmbeddingProvider → null vector
- Native 384-dim from all-MiniLM-L6-v2 (no padding)
- Async API compatible with causal_module.py

USAGE:
    embedder = get_embedder()
    vector = await embedder.embed("text")  # → list[float] (384 dims)
"""
from __future__ import annotations

import os
import structlog

log = structlog.get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 native dimension


class EmbeddingProvider:
    """Lightweight embedder for causal module (384-dim)."""

    def __init__(self):
        self._sentence_model = None
        self._openai_client = None
        self._fallback_provider = None
        self._use_openai = bool(os.getenv("OPENAI_API_KEY"))

    async def embed(self, text: str) -> list[float]:
        """
        Embed text to 384-dimensional vector.
        
        Fallback chain:
        1. sentence-transformers all-MiniLM-L6-v2 (native 384-dim)
        2. OpenAI text-embedding-3-small (truncate 1536 → 384)
        3. memory.embeddings.EmbeddingProvider (extract first 384 dims)
        4. Null vector [0.0] * 384
        """
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM

        # Try sentence-transformers first (native 384-dim)
        try:
            vector = await self._embed_sentence_transformer(text)
            if vector:
                return vector
        except Exception as e:
            log.warning("sentence_transformer_embed_failed", error=str(e))

        # Try OpenAI second
        if self._use_openai:
            try:
                vector = await self._embed_openai(text)
                if vector:
                    return vector[:EMBEDDING_DIM]  # Truncate to 384
            except Exception as e:
                log.warning("openai_embed_failed", error=str(e))
                self._use_openai = False  # Disable for session

        # Fallback to memory.embeddings.EmbeddingProvider
        try:
            vector = await self._embed_fallback(text)
            if vector:
                return vector[:EMBEDDING_DIM]  # Extract first 384
        except Exception as e:
            log.warning("fallback_embed_failed", error=str(e))

        # Final fallback: null vector
        log.error("embed_null_vector", reason="all_providers_failed")
        return [0.0] * EMBEDDING_DIM
    
    async def _embed_sentence_transformer(self, text: str) -> list[float] | None:
        """Embed using sentence-transformers (native 384-dim)."""
        if not self._sentence_model:
            try:
                from sentence_transformers import SentenceTransformer
                log.info("loading_sentence_transformer", model="all-MiniLM-L6-v2")
                self._sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
                log.info("sentence_transformer_loaded", model="all-MiniLM-L6-v2")
            except ImportError:
                log.warning("sentence_transformers_not_installed")
                return None
            except Exception as e:
                log.error("sentence_transformer_load_failed", error=str(e))
                return None

        try:
            # Run in thread pool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            vector = await loop.run_in_executor(
                None, 
                lambda: self._sentence_model.encode(text, convert_to_numpy=True).tolist()
            )
            log.debug("sentence_transformer_embed_success", dim=len(vector))
            return vector
        except Exception as e:
            log.error("sentence_transformer_encode_error", error=str(e))
            return None

    async def _embed_openai(self, text: str) -> list[float] | None:
        """Embed using OpenAI API."""
        if not self._openai_client:
            try:
                import openai
                self._openai_client = openai.AsyncOpenAI(
                    api_key=os.getenv("OPENAI_API_KEY")
                )
            except ImportError:
                log.warning("openai_not_installed")
                return None

        try:
            response = await self._openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            log.error("openai_embed_error", error=str(e))
            return None

    async def _embed_fallback(self, text: str) -> list[float] | None:
        """Embed using memory.embeddings.EmbeddingProvider."""
        if not self._fallback_provider:
            try:
                from memory.embeddings import EmbeddingProvider as MemoryEmbedder
                from config import Settings
                settings = Settings()
                self._fallback_provider = MemoryEmbedder(settings)
            except Exception as e:
                log.warning("fallback_provider_init_failed", error=str(e))
                return None

        try:
            # EmbeddingProvider returns 1536-dim by default
            # Extract first 384 dims (native all-MiniLM-L6-v2 before padding)
            vector = await self._fallback_provider.embed(text)
            return vector[:EMBEDDING_DIM]
        except Exception as e:
            log.error("fallback_embed_error", error=str(e))
            return None


# ── Singleton accessor ────────────────────────────────────────────────────────

_embedder: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    """Get singleton embedding provider."""
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingProvider()
    return _embedder


# ── Convenience API ───────────────────────────────────────────────────────────

async def embed_text(text: str) -> list[float]:
    """
    Embed text to 384-dimensional vector.
    
    Convenience wrapper around get_embedder().embed().
    """
    embedder = get_embedder()
    return await embedder.embed(text)
