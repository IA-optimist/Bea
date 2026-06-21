"""Recall from Bea's canonical Qdrant memory collection.

The seeded long-term memory lives in ``beamax_memory_384`` with
all-MiniLM-L6-v2 embeddings. This module keeps that path small and fail-open
so agents can retrieve context without coupling the rest of MemoryBus to
Qdrant client internals.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

DEFAULT_COLLECTION = "beamax_memory_384"
DEFAULT_MODEL = "all-MiniLM-L6-v2"


@dataclass(frozen=True)
class QdrantRecallConfig:
    url: str
    api_key: str
    collection: str = DEFAULT_COLLECTION
    model_name: str = DEFAULT_MODEL


def _settings_value(settings: Any, name: str, default: str = "") -> str:
    value = getattr(settings, name, "")
    return str(value) if value else default


def config_from_settings(settings: Any) -> QdrantRecallConfig:
    """Build recall config from settings/env without exposing secrets."""
    url = (
        _settings_value(settings, "qdrant_url")
        or os.environ.get("QDRANT_URL")
        or "http://127.0.0.1:6333"
    )
    api_key = (
        _settings_value(settings, "qdrant_api_key")
        or os.environ.get("QDRANT_API_KEY")
        or ""
    )
    collection = (
        os.environ.get("BEA_MEMORY_COLLECTION")
        or os.environ.get("QDRANT_COLLECTION")
        or DEFAULT_COLLECTION
    )
    return QdrantRecallConfig(
        url=url.rstrip("/"),
        api_key=api_key,
        collection=collection,
    )


class QdrantMemoryRecall:
    """Small fail-open semantic recall adapter for ``beamax_memory_384``."""

    def __init__(self, config: QdrantRecallConfig) -> None:
        self.config = config
        self._model: Any = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["api-key"] = self.config.api_key
        return headers

    def _encoder(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.config.model_name)
        return self._model

    def _encode(self, text: str) -> list[float]:
        vector = self._encoder().encode(text, normalize_embeddings=True)
        return vector.tolist()

    def search(self, query: str, top_k: int = 5, min_score: float = 0.25) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        try:
            import httpx

            vector = self._encode(query)
            body: dict[str, Any] = {
                "vector": vector,
                "limit": top_k,
                "score_threshold": min_score,
                "with_payload": True,
            }
            response = httpx.post(
                f"{self.config.url}/collections/{self.config.collection}/points/search",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            response.raise_for_status()
            return [self._to_memory_result(hit) for hit in response.json().get("result", [])]
        except Exception as exc:
            log.warning(
                "qdrant_recall_failed",
                collection=self.config.collection,
                err=str(exc)[:120],
            )
            return []

    def _to_memory_result(self, hit: dict[str, Any]) -> dict[str, Any]:
        payload = hit.get("payload") or {}
        metadata = {
            "key": payload.get("key", ""),
            "tags": payload.get("tags", []),
            "category": payload.get("category", ""),
            "source": payload.get("source", ""),
            "ts": payload.get("ts"),
        }
        return {
            "id": str(hit.get("id", "")),
            "text": str(payload.get("text", "")),
            "score": float(hit.get("score", 0.0)),
            "metadata": metadata,
            "backend": "qdrant_beamax",
        }
