"""
docker/github-mcp/app.py — GitHub MCP HTTP sidecar (read-only).

Exposes Bea /invoke endpoint protocol (POST /invoke) backed by gh CLI.
Compatible with Bea MCPAdapter.

Tools (read-only — write tools are NOT implemented, approval required):
  github_search_code  — search code across repositories
  github_list_issues  — list open/closed issues for a repo

Security:
  - GITHUB_PERSONAL_ACCESS_TOKEN must be set in sidecar env only
  - Write tools (create_pr, push_files) intentionally absent — requires_approval=True
  - Token never returned in API responses

Env:
  GITHUB_PERSONAL_ACCESS_TOKEN  (required)

Usage:
  docker build -t bea-github-mcp .
  docker run -p 3000:3000 -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx bea-github-mcp
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger("github-mcp")

GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")

app = FastAPI(title="GitHub MCP Sidecar (read-only)", version="1.0.0")


class InvokeRequest(BaseModel):
    tool: str
    params: dict = {}
    context: dict = {}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    if not GITHUB_TOKEN:
        return {
            "ok": False,
            "service": "github-mcp",
            "error": "GITHUB_PERSONAL_ACCESS_TOKEN not set",
        }
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "GH_TOKEN": GITHUB_TOKEN, "GITHUB_TOKEN": GITHUB_TOKEN},
        )
        ok = result.returncode == 0
        return {"ok": ok, "service": "github-mcp"}
    except Exception as e:
        return {"ok": False, "service": "github-mcp", "error": str(e)[:120]}


# ── Invoke ────────────────────────────────────────────────────────────────────

@app.post("/invoke")
def invoke(req: InvokeRequest):
    try:
        if req.tool == "github_search_code":
            return _search_code(req.params)
        elif req.tool == "github_list_issues":
            return _list_issues(req.params)
        else:
            return {
                "ok": False,
                "error": (
                    f"Tool {req.tool!r} not available in read-only mode. "
                    "Available: github_search_code, github_list_issues"
                ),
            }
    except Exception as exc:
        log.error("github_mcp_invoke_error", tool=req.tool, error=str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300]}


# ── Tool implementations ──────────────────────────────────────────────────────

def _gh(*args) -> list | dict:
    """Run gh CLI command, return parsed JSON. Raises RuntimeError on failure."""
    cmd = ["gh"] + list(args)
    env = {**os.environ, "GITHUB_TOKEN": GITHUB_TOKEN, "GH_TOKEN": GITHUB_TOKEN}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    if not result.stdout.strip():
        return []
    return json.loads(result.stdout)


def _search_code(params: dict) -> dict:
    query = params.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    repo = params.get("repo", "").strip()
    full_query = f"{query} repo:{repo}" if repo else query

    data = _gh(
        "search", "code", full_query,
        "--json", "path,repository,url",
        "--limit", "10",
    )
    log.info("github_search_code",
             query=query[:40], results=len(data) if isinstance(data, list) else 0)
    return {"ok": True, "results": data, "query": query}


def _list_issues(params: dict) -> dict:
    repo = params.get("repo", "").strip()
    if not repo:
        return {"ok": False, "error": "repo is required (format: owner/repo)"}
    state = params.get("state", "open")
    limit = str(min(int(params.get("limit", 20)), 100))

    data = _gh(
        "issue", "list",
        "--repo", repo,
        "--state", state,
        "--limit", limit,
        "--json", "number,title,state,url,createdAt",
    )
    log.info("github_list_issues",
             repo=repo, state=state, results=len(data) if isinstance(data, list) else 0)
    return {"ok": True, "issues": data, "repo": repo}
