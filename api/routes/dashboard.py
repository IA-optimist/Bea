"""
Dashboard status route — GET /dashboard/status
Agrège l'état du système en un seul JSON. Tout fail-open.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess  # nosec B404

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api._deps import _check_auth
from typing import Optional as _Opt
from fastapi import Header

def _auth(x_jarvis_token: _Opt[str] = Header(None), authorization: _Opt[str] = Header(None)):
    _check_auth(x_jarvis_token, authorization)


router = APIRouter(tags=["dashboard"], dependencies=[Depends(_auth)])

_START_TIME = datetime.datetime.now(datetime.timezone.utc)


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except Exception:
        return None


def _git_info() -> dict:
    try:
        out = subprocess.check_output(  # nosec B603 B607
            ["git", "log", "-1", "--format=%H|||%s|||%ad", "--date=iso"],
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        parts = out.split("|||")
        return {
            "commit": parts[0] if parts else None,
            "subject": parts[1] if len(parts) > 1 else None,
            "date": parts[2] if len(parts) > 2 else None,
            "branch": subprocess.check_output(  # nosec B603 B607
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                timeout=3, stderr=subprocess.DEVNULL,
            ).decode().strip(),
        }
    except Exception:
        return {"commit": None, "branch": None}


def _feature_flags() -> dict:
    return {
        "USE_LANGGRAPH": os.getenv("USE_LANGGRAPH", "false"),
        "USE_TOOL_INTELLIGENCE": os.getenv("USE_TOOL_INTELLIGENCE", "false"),
        "USE_KNOWLEDGE_EXPANSION": os.getenv("USE_KNOWLEDGE_EXPANSION", "false"),
    }


def _tool_stats() -> dict:
    try:
        obs_path = pathlib.Path("workspace/tool_intelligence/observations.json")
        data = _read_json(obs_path)
        if not isinstance(data, list):
            return {"observations_count": 0, "top_tools": []}
        tool_counts: dict[str, int] = {}
        for entry in data:
            t = entry.get("tool_name", "unknown")
            tool_counts[t] = tool_counts.get(t, 0) + 1
        top = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
        return {"observations_count": len(data), "top_tools": [{"tool": k, "count": v} for k, v in top]}
    except Exception:
        return {"observations_count": None, "top_tools": None}


def _knowledge_stats() -> dict:
    try:
        entries_path = pathlib.Path("workspace/knowledge_expansion/entries.json")
        data = _read_json(entries_path)
        if not isinstance(data, list):
            return {"entries_count": 0, "expired_count": 0}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        expired = sum(1 for e in data if e.get("expires_at") and e["expires_at"] < now)
        return {"entries_count": len(data), "expired_count": expired}
    except Exception:
        return {"entries_count": None, "expired_count": None}


def _approval_stats() -> dict:
    try:
        from core.approval_queue import get_pending
        return {"pending_count": len(get_pending())}
    except Exception:
        return {"pending_count": None}


def _tests_summary() -> dict:
    try:
        p = pathlib.Path("workspace/test_results.json")
        data = _read_json(p)
        if not data:
            return {"last_run_date": None, "passed": None, "failed": None}
        return {
            "last_run_date": data.get("date"),
            "passed": data.get("passed"),
            "failed": data.get("failed"),
        }
    except Exception:
        return {"last_run_date": None, "passed": None, "failed": None}


def _qdrant_health() -> dict:
    try:
        import urllib.request
        qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
        url = f"http://{qdrant_host}:6333/collections"
        with urllib.request.urlopen(url, timeout=2) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
            data = json.loads(resp.read())
            collections = [c["name"] for c in data.get("result", {}).get("collections", [])]
            return {"status": "ok", "collections": collections}
    except Exception as e:
        return {"status": "unavailable", "error": str(e)[:80]}


@router.get("/dashboard/status")
async def dashboard_status():
    uptime = (datetime.datetime.now(datetime.timezone.utc) - _START_TIME).total_seconds()
    return JSONResponse({
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "api_health": {
            "status": "ok",
            "version": os.getenv("JARVIS_VERSION", "unknown"),
            "uptime_seconds": round(uptime, 1),
        },
        "feature_flags": _feature_flags(),
        "tool_stats": _tool_stats(),
        "knowledge_stats": _knowledge_stats(),
        "approval_queue": _approval_stats(),
        "qdrant_health": _qdrant_health(),
        "tests_summary": _tests_summary(),
        "git_info": _git_info(),
    })
