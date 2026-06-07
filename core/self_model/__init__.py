"""
core/self_model/ — BeaMax Self-Model layer.

A structured introspection system that lets Bea reason about its own
operational state: capabilities, limits, readiness, and autonomy boundaries.

Public API:
    from core.self_model import build_self_model, query, serialize

    model = build_self_model()
    ready = query.what_can_i_do(model)
    context = serialize.to_llm_context(model)
"""
from core.self_model.updater import build_self_model
from core.self_model import queries as query
from core.self_model import serializer as serialize

__all__ = ["build_self_model", "query", "serialize"]
