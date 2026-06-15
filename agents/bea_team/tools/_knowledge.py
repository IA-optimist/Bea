"""Knowledge interaction tools for bea-team agents."""
from __future__ import annotations

import time

import structlog

from ._base import REPO_ROOT, ToolResult, _timed

log = structlog.get_logger(__name__)


@_timed
def tool_store_pattern(pattern_type: str, problem: str, solution: str,
                       confidence: float = 0.5, tags: list[str] | None = None) -> ToolResult:
    """Store a structured solution pattern. Requires confidence score."""
    if not 0.0 <= confidence <= 1.0:
        return ToolResult(success=False, tool="store_pattern", error="Confidence must be 0.0-1.0")
    try:
        from core.tools.memory_toolkit import memory_store_solution
        result = memory_store_solution(
            problem=f"[{pattern_type}] {problem}",
            solution=solution,
            tags=(tags or []) + [pattern_type],
        )
        return ToolResult(
            success=result.get("ok", False), tool="store_pattern",
            data={"confidence": confidence, "type": pattern_type},
            error=result.get("error", ""),
        )
    except Exception:
        import json as _json
        store_path = REPO_ROOT / "workspace" / "knowledge_store.jsonl"
        try:
            store_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "type": pattern_type, "problem": problem[:500],
                "solution": solution[:500], "confidence": confidence,
                "tags": tags or [], "timestamp": time.time(),
            }
            with open(store_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry) + "\n")
            return ToolResult(
                success=True, tool="store_pattern",
                data={"stored_locally": True, "confidence": confidence},
            )
        except Exception as e2:
            return ToolResult(success=False, tool="store_pattern", error=str(e2)[:300])


@_timed
def tool_search_patterns(query: str, limit: int = 5) -> ToolResult:
    """Search past solution patterns by keyword."""
    try:
        from core.tools.memory_toolkit import memory_search_similar
        result = memory_search_similar(query=query, limit=limit)
        return ToolResult(
            success=result.get("ok", False), tool="search_patterns",
            data=result.get("results", []),
            error=result.get("error", ""),
        )
    except Exception:
        import json as _json
        store_path = REPO_ROOT / "workspace" / "knowledge_store.jsonl"
        if not store_path.exists():
            return ToolResult(success=True, tool="search_patterns", data=[])
        matches = []
        q_lower = query.lower()
        try:
            for line in store_path.read_text().splitlines():
                entry = _json.loads(line)
                if q_lower in entry.get("problem", "").lower() or q_lower in entry.get("solution", "").lower():
                    matches.append(entry)
                if len(matches) >= limit:
                    break
        except Exception as _exc:
            log.warning("swallowed_exception", action="tools_swallow",
                        exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return ToolResult(success=True, tool="search_patterns", data=matches)


@_timed
def tool_store_decision(decision: str, rationale: str, impact: str,
                        confidence: float = 0.5) -> ToolResult:
    """Store an architecture decision record."""
    import json as _json
    store_path = REPO_ROOT / "workspace" / "decisions.jsonl"
    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "decision": decision[:500], "rationale": rationale[:500],
            "impact": impact[:300], "confidence": confidence,
            "timestamp": time.time(),
        }
        with open(store_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry) + "\n")
        return ToolResult(
            success=True, tool="store_decision",
            data={"stored": True, "confidence": confidence},
        )
    except Exception as e:
        return ToolResult(success=False, tool="store_decision", error=str(e)[:300])
