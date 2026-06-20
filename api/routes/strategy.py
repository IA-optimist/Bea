"""
api/routes/strategy.py — Strategy comparison and auto-promotion API.

Endpoints:
  GET  /api/v3/strategy/defaults    — current default strategies
  GET  /api/v3/strategy/compare     — compare strategies for a task type
  GET  /api/v3/strategy/promotions  — promotion history
  POST /api/v3/strategy/check       — check for pending promotions
  GET  /api/v3/strategy/status      — overall strategy registry status
  GET  /api/v3/strategy/records     — raw strategy records
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

# Fail-hard on auth import: a None fallback would make Depends(None) a
# pass-through, creating a silent auth bypass.
from api._deps import require_auth

router = APIRouter(prefix="/api/v3/strategy", tags=["strategy"])


@router.get("/defaults")  # type: ignore[untyped-decorator]
async def get_defaults(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    """Get current default strategies for all task types."""
    try:
        from core.execution.strategy_registry import get_strategy_registry
        return {"ok": True, "defaults": get_strategy_registry().get_all_defaults()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.get("/compare")  # type: ignore[untyped-decorator]
async def compare_strategies(
    task_type: str = Query(...),
    user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Compare all strategies for a specific task type."""
    try:
        from core.execution.strategy_memory import get_strategy_memory
        comparison = get_strategy_memory().compare(task_type)
        return {"ok": True, "comparison": comparison.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.get("/promotions")  # type: ignore[untyped-decorator]
async def get_promotions(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    """Get strategy promotion history."""
    try:
        from core.execution.strategy_registry import get_strategy_registry
        return {
            "ok": True,
            "promotions": get_strategy_registry().get_promotion_history(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.post("/check")  # type: ignore[untyped-decorator]
async def check_promotions(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    """Check and execute pending promotions across all task types."""
    try:
        from core.execution.strategy_registry import get_strategy_registry
        events = get_strategy_registry().check_all_promotions()
        return {
            "ok": True,
            "promotions_executed": len(events),
            "events": [e.to_dict() for e in events],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.get("/status")  # type: ignore[untyped-decorator]
async def strategy_status(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    """Overall strategy registry status."""
    try:
        from core.execution.strategy_registry import get_strategy_registry
        from core.execution.strategy_memory import get_strategy_memory
        reg = get_strategy_registry()
        mem = get_strategy_memory()
        return {
            "ok": True,
            "registry": reg.get_status(),
            "memory_records": len(mem._records),
            "comparisons": [c.to_dict() for c in mem.get_all_comparisons()],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


@router.get("/records")  # type: ignore[untyped-decorator]
async def get_records(
    task_type: str = "", limit: int = Query(50, ge=1, le=200),
    user: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Get raw strategy records."""
    try:
        from core.execution.strategy_memory import get_strategy_memory
        return {
            "ok": True,
            "records": get_strategy_memory().get_records(task_type=task_type, limit=limit),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
