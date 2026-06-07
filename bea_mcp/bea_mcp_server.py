"""
bea_mcp/bea_mcp_server.py — Bea MCP server (FastMCP).

Expose Bea tools via the MCP protocol so any MCP-compatible client
(Claude Desktop, Claude Code, other agents) can call Bea directly.

Feature flag : MCP_SERVER_ENABLED=true
Dependency   : mcp>=1.0.0  (pip install mcp)
Transport    : stdio (default) or SSE

Tools exposed (read-safe, no state mutation):
  - memory_search(query, top_k)   → vector memory search
  - mission_status(mission_id)    → read a mission from workspace
  - list_missions(limit)          → list recent missions

Startup (standalone):
    python -m bea_mcp.bea_mcp_server

Or use stdio transport with Claude Desktop / Claude Code:
    {
      "mcpServers": {
        "bea": {
          "command": "python3",
          "args": ["/app/bea_mcp/bea_mcp_server.py"],
          "env": { "PYTHONPATH": "/app" }
        }
      }
    }

Security:
  - Read-only tools only (no mission submission, no action execution)
  - BEA_MCP_ALLOWED_ORIGINS env var for SSE CORS (default: localhost only)
  - No secrets exposed via tool responses
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger("bea_mcp.bea_server")

# ── FastMCP import guard ──────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    FastMCP = None  # type: ignore

# ── Workspace resolution (no settings import to keep server standalone) ───────
_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/app/workspace"))
_MISSIONS_DIR = _WORKSPACE / "missions"


def _build_server() -> Any:
    """Build the FastMCP server with all Bea tools."""
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "mcp package not installed. Run: pip install 'mcp>=1.0.0'"
        )

    mcp = FastMCP(
        name="bea",
        description="Bea Max — Autonomous AI agent system",
        version="1.0.0",
    )

    # ── Tool 1: memory_search ─────────────────────────────────────────────────

    @mcp.tool()
    def memory_search(query: str, top_k: int = 5) -> str:
        """
        Search Bea vector memory for relevant context.

        Args:
            query:  The search query (natural language).
            top_k:  Maximum number of results to return (1-20).

        Returns:
            JSON string with list of matching memories:
            [{"id": "...", "text": "...", "score": 0.87, "metadata": {...}}, ...]
        """
        top_k = max(1, min(top_k, 20))
        try:
            # Lazy import to avoid circular deps when run standalone
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from config.settings import get_settings
            from memory.vector_memory import VectorMemory

            settings = get_settings()
            vm = VectorMemory(settings)
            results = vm.search(query, top_k=top_k)
            return json.dumps(results, ensure_ascii=False)
        except Exception as exc:
            log.warning("mcp_memory_search_failed", error=str(exc))
            return json.dumps({"error": str(exc), "results": []})

    # ── Tool 2: mission_status ────────────────────────────────────────────────

    @mcp.tool()
    def mission_status(mission_id: str) -> str:
        """
        Get the current status and result of a Bea mission.

        Args:
            mission_id: The mission ID (e.g. "mission_abc123").

        Returns:
            JSON string with mission details:
            {"id": "...", "status": "DONE", "goal": "...", "result": "..."}
        """
        if not mission_id or "/" in mission_id or ".." in mission_id:
            return json.dumps({"error": "Invalid mission_id"})
        try:
            mission_file = _MISSIONS_DIR / f"{mission_id}.json"
            if not mission_file.exists():
                return json.dumps({"error": f"Mission {mission_id!r} not found"})
            with open(mission_file, encoding="utf-8") as f:
                data = json.load(f)
            # Filter: return only safe, non-sensitive fields
            safe = {
                "id":         data.get("id", mission_id),
                "status":     data.get("status", "UNKNOWN"),
                "goal":       data.get("user_input", data.get("goal", "")),
                "result":     data.get("final_output", data.get("result", "")),
                "created_at": data.get("created_at", ""),
                "completed_at": data.get("completed_at"),
                "intent":     data.get("intent", ""),
                "plan_summary": data.get("plan_summary", ""),
            }
            return json.dumps(safe, ensure_ascii=False)
        except Exception as exc:
            log.warning("mcp_mission_status_failed", error=str(exc))
            return json.dumps({"error": str(exc)})

    # ── Tool 3: list_missions ─────────────────────────────────────────────────

    @mcp.tool()
    def list_missions(limit: int = 10) -> str:
        """
        List the most recent Bea missions.

        Args:
            limit: Maximum number of missions to return (1-50).

        Returns:
            JSON string with list of missions (summary only):
            [{"id": "...", "status": "...", "goal": "...", "created_at": "..."}, ...]
        """
        limit = max(1, min(limit, 50))
        try:
            if not _MISSIONS_DIR.exists():
                return json.dumps([])
            files = sorted(
                _MISSIONS_DIR.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:limit]
            results = []
            for f in files:
                try:
                    with open(f, encoding="utf-8") as fp:
                        d = json.load(fp)
                    results.append({
                        "id":         d.get("id", f.stem),
                        "status":     d.get("status", "UNKNOWN"),
                        "goal":       (d.get("user_input", d.get("goal", "")) or "")[:200],
                        "created_at": d.get("created_at", ""),
                    })
                except Exception:
                    continue
            return json.dumps(results, ensure_ascii=False)
        except Exception as exc:
            log.warning("mcp_list_missions_failed", error=str(exc))
            return json.dumps({"error": str(exc), "missions": []})

    return mcp


# ── Startup guard ─────────────────────────────────────────────────────────────

def run_stdio():
    """Run the MCP server in stdio transport mode (for Claude Desktop / Code)."""
    if not _MCP_AVAILABLE:
        print(
            "ERROR: mcp package not installed. Run: pip install 'mcp>=1.0.0'",
            file=sys.stderr,
        )
        sys.exit(1)
    server = _build_server()
    server.run(transport="stdio")


def get_mcp_server():
    """Return the FastMCP instance (for testing or SSE embedding)."""
    return _build_server()


if __name__ == "__main__":
    run_stdio()
