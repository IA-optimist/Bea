"""
BEA MAX — Grounded LLM
Combines RAG retrieval with LLM generation for grounded answers.

Usage:
    answer = await ask("What does ingest_file do?", context_docs=["..."])
    answer = await ask_codebase("How does the orchestrator handle fallbacks?")
"""
from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_MAX_CONTEXT_CHARS = 12_000   # ~3k tokens — safe for gpt-4o-mini context window
_RAG_PROMPT_TEMPLATE = """\
[CONTEXT]
{context}

[QUESTION]
{question}

Answer the question based strictly on the provided context. \
If the context does not contain enough information to answer, say so clearly. \
Be concise and precise."""


# ── Core: ask ────────────────────────────────────────────────

async def ask(
    question:     str,
    context_docs: list[str] | None = None,
    system_prompt: str = "You are a helpful assistant that answers questions based on provided context.",
) -> str:
    """
    Build a grounded RAG prompt from context_docs and call LLM.
    Falls back to direct LLM call if no context provided.
    Returns answer string.
    """
    if not context_docs:
        context = "[No context provided]"
    else:
        # Truncate to fit context window
        joined  = "\n\n---\n\n".join(context_docs)
        context = joined[:_MAX_CONTEXT_CHARS]
        if len(joined) > _MAX_CONTEXT_CHARS:
            context += "\n[... context truncated ...]"

    prompt = _RAG_PROMPT_TEMPLATE.format(context=context, question=question)

    # Try LLMFactory first (LangChain)
    try:
        from config.settings import get_settings
        from core.llm_factory import LLMFactory
        llm     = LLMFactory(get_settings()).get("default")
        from langchain_core.messages import HumanMessage, SystemMessage
        msgs    = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        resp    = await llm.ainvoke(msgs)
        answer  = resp.content if hasattr(resp, "content") else str(resp)
        log.info("grounded_llm_answered", question_len=len(question), answer_len=len(answer))
        return answer
    except Exception as e:
        log.debug("grounded_llm_langchain_failed", err=str(e)[:80])

    # Fallback: direct OpenAI
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        try:
            import openai as _openai
            client = _openai.AsyncOpenAI(api_key=api_key)
            resp   = await client.chat.completions.create(
                model    = "gpt-4o-mini",
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens = 1024,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            log.warning("grounded_llm_openai_failed", err=str(e)[:80])

    return f"[LLM unavailable — context retrieved but no LLM to answer. Context preview: {context[:300]}]"


# ── Core: ask_codebase ────────────────────────────────────────

async def ask_codebase(
    question: str,
    top_k:    int   = 6,
    min_score: float = 0.25,
) -> dict[str, Any]:
    """
    Full pipeline: query → retrieve → grounded answer.
    Returns dict with answer + sources + scores.
    """
    from core.rag.pipeline import get_rag_pipeline
    pipeline = get_rag_pipeline()

    rag_result = await pipeline.query(question, top_k=top_k, min_score=min_score)

    if not rag_result.ok:
        answer = await ask(question, context_docs=None)
        return {
            "answer":   answer,
            "sources":  [],
            "scores":   [],
            "retrieved": 0,
            "grounded": False,
        }

    answer = await ask(question, context_docs=rag_result.chunks)

    return {
        "answer":   answer,
        "sources":  rag_result.sources,
        "scores":   [round(s, 4) for s in rag_result.scores],
        "retrieved": rag_result.total_found,
        "grounded": True,
    }
