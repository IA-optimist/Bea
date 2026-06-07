"""
BEA MAX — RAG API Routes

POST /api/v2/rag/index    — index a file or text
POST /api/v2/rag/query    — semantic search
POST /api/v2/rag/ask      — grounded question answering
GET  /api/v2/rag/status   — index stats
"""
from __future__ import annotations

import os
from typing import Any, Optional

import structlog
from fastapi import Depends, APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_bea_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_bea_token, authorization)



router = APIRouter(prefix="/api/v2/rag", tags=["rag"], dependencies=[Depends(_auth)])

_API_TOKEN = os.getenv("BEA_API_TOKEN", "")


# ── Request models ────────────────────────────────────────────

class IndexRequest(BaseModel):
    path:     Optional[str]        = None
    text:     Optional[str]        = None
    metadata: dict[str, Any]       = Field(default_factory=dict)
    force:    bool                 = False


class QueryRequest(BaseModel):
    question:  str   = Field(..., min_length=1)
    top_k:     int   = Field(5, ge=1, le=20)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


class AskRequest(BaseModel):
    question:  str   = Field(..., min_length=1)
    top_k:     int   = Field(6, ge=1, le=20)
    min_score: float = Field(0.25, ge=0.0, le=1.0)


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/index")
async def rag_index(
    req: IndexRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Index a file (by path) or inline text into the vector store."""
    from core.rag.pipeline import get_rag_pipeline

    if not req.path and not req.text:
        raise HTTPException(status_code=422, detail="Provide 'path' or 'text'.")

    pipeline = get_rag_pipeline()

    if req.path:
        result = await pipeline.index_document(req.path, metadata=req.metadata, force=req.force)
    else:
        # Inline text: ingest_text then index
        from core.rag.ingestion import ingest_text
        doc    = await ingest_text(req.text, metadata=req.metadata)  # type: ignore[arg-type]
        result = await pipeline.index_document(doc.content, metadata=req.metadata, force=req.force)

    return {"ok": True, "data": result}


@router.post("/query")
async def rag_query(
    req: QueryRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Semantic search over indexed documents."""
    from core.rag.pipeline import get_rag_pipeline

    pipeline   = get_rag_pipeline()
    rag_result = await pipeline.query(
        question  = req.question,
        top_k     = req.top_k,
        min_score = req.min_score,
    )

    return {"ok": True, "data": rag_result.to_dict()}


@router.post("/ask")
async def rag_ask(
    req: AskRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Full grounded QA: retrieve context + LLM answer."""
    from core.rag.grounded_llm import ask_codebase

    result = await ask_codebase(
        question  = req.question,
        top_k     = req.top_k,
        min_score = req.min_score,
    )
    return {"ok": True, "data": result}


@router.get("/status")
async def rag_status(x_bea_token: Optional[str] = Header(None)):
    """Index statistics."""
    from core.rag.pipeline import get_rag_pipeline

    pipeline = get_rag_pipeline()
    status   = await pipeline.status()
    return {"ok": True, "data": status}
