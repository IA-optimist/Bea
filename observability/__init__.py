"""
BEA MAX — Observability layer
Traçage LLM via Langfuse (optionnel, self-hosted).
"""
from .langfuse_tracer import LangfuseTracer, get_tracer

__all__ = ["LangfuseTracer", "get_tracer"]
