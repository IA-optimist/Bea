"""
docker/qdrant-mcp/app.py — Qdrant MCP HTTP sidecar.

Exposes Bea /invoke endpoint protocol (POST /invoke) backed by qdrant-client.
Compatible with Bea MCPAdapter.

Tools:
  qdrant_search  — scroll search (or vector if pre-computed embedding provided)
  qdrant_upsert  — upsert a point with vector + payload

Env:
  QDRANT_URL        (default: http://qdrant:6333)
  QDRANT_API_KEY    (default: empty)
  QDRANT_COLLECTION (default: bea_memory)

Usage:
  docker build -t bea-qdrant-mcp .
  docker run -p 8000:8000 -e QDRANT_URL=http://qdrant:6333 bea-qdrant-mcp
"""
from __future__ import annotations

import logging
import os

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger("qdrant-mcp")

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", "") or None
DEFAULT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "bea_memory")

app = FastAPI(title="Qdrant MCP Sidecar", version="1.0.0")


def _client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


class InvokeRequest(BaseModel):
    tool: str
    params: dict = {}
    context: dict = {}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        c = _client()
        collections = c.get_collections()
        return {
            "ok": True,
            "service": "qdrant-mcp",
            "qdrant_url": QDRANT_URL,
            "collections": len(collections.collections),
        }
    except Exception as e:
        return {"ok": False, "service": "qdrant-mcp", "error": str(e)[:120]}


# ── Invoke ────────────────────────────────────────────────────────────────────

@app.post("/invoke")
def invoke(req: InvokeRequest):
    try:
        if req.tool == "qdrant_search":
            return _search(req.params)
        elif req.tool == "qdrant_upsert":
            return _upsert(req.params)
        else:
            return {
                "ok": False,
                "error": (
                    f"Unknown tool: {req.tool!r}. "
                    "Available: qdrant_search, qdrant_upsert"
                ),
            }
    except Exception as exc:
        log.error("qdrant_mcp_invoke_error", tool=req.tool, error=str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}


# ── Tool implementations ──────────────────────────────────────────────────────

def _search(params: dict) -> dict:
    query = params.get("query", "")
    top_k = int(params.get("top_k", 5))
    collection = params.get("collection", DEFAULT_COLLECTION)
    vector = params.get("vector")  # optional pre-computed embedding

    c = _client()

    if vector:
        # Semantic search with provided vector
        hits = c.search(
            collection_name=collection,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )
        results = [
            {"id": str(h.id), "payload": h.payload, "score": h.score}
            for h in hits
        ]
    else:
        # Scroll search — returns stored payloads without vector requirement
        scroll_result, _ = c.scroll(
            collection_name=collection,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        results = [
            {"id": str(p.id), "payload": p.payload, "score": None}
            for p in scroll_result
        ]

    log.info("qdrant_search",
             collection=collection, query=query[:40], results=len(results))
    return {"ok": True, "results": results, "query": query, "collection": collection}


def _upsert(params: dict) -> dict:
    from qdrant_client.models import PointStruct

    collection = params.get("collection", DEFAULT_COLLECTION)
    point_id = params.get("id")
    if point_id is None:
        return {"ok": False, "error": "id is required for upsert"}
    vector = params.get("vector", [])
    payload = params.get("payload", {})

    c = _client()
    c.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )
    log.info("qdrant_upsert", collection=collection, id=point_id)
    return {"ok": True, "upserted": point_id, "collection": collection}
