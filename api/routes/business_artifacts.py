"""
api/routes/business_artifacts.py — Browse generated business artifacts.

Scoped to workspace/business/. Read-only file access.
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api._deps import require_auth
_silent_log = __import__("structlog").get_logger(__name__)

router = APIRouter(prefix="/api/v3/business-artifacts", tags=["business-artifacts"])

_WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "workspace"))
_BUSINESS_DIR = _WORKSPACE / "business"

# Allowed extensions for content read (no binaries)
_TEXT_EXTENSIONS = {".md", ".json", ".txt", ".csv", ".yaml", ".yml", ".toml"}


def _safe_path(base: Path, *parts: str) -> Path:
    """Resolve path and ensure it's within the base directory."""
    resolved = base.joinpath(*parts).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise HTTPException(403, "Path traversal blocked")
    return resolved


# ── Endpoints ─────────────────────────────────────────────────

@router.get("/runs")
async def list_runs(_user: dict = Depends(require_auth)):
    """List all business runs (project directories)."""
    if not _BUSINESS_DIR.is_dir():
        return {"ok": True, "data": []}

    runs = []
    for entry in sorted(_BUSINESS_DIR.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        files = list(entry.iterdir())
        # Extract metadata from directory name pattern: slug-YYYYMMDD-HHMM
        name = entry.name
        parts = name.rsplit("-", 2)
        timestamp = ""
        if len(parts) >= 3:
            try:
                timestamp = f"{parts[-2][:4]}-{parts[-2][4:6]}-{parts[-2][6:8]} {parts[-1][:2]}:{parts[-1][2:]}"
            except (IndexError, ValueError):
                _silent_log.debug("suppressed_exception", src='business_artifacts.py')

        # Detect action_id from files
        action_id = ""
        if any(f.name == "opportunities.json" for f in files):
            action_id = "venture.research_workspace"
        elif any(f.name == "offer-spec.json" for f in files):
            action_id = "offer.package"
        elif any(f.name == "workflows.json" for f in files):
            action_id = "workflow.blueprint"
        elif any(f.name == "mvp-spec.json" for f in files):
            action_id = "saas.mvp_spec"
        elif any(f.name == "trigger-result.json" for f in files):
            action_id = "workflow.n8n_trigger"

        runs.append({
            "run_id": name,
            "action_id": action_id,
            "timestamp": timestamp,
            "file_count": len([f for f in files if f.is_file()]),
            "total_size": sum(f.stat().st_size for f in files if f.is_file()),
            "created_at": entry.stat().st_mtime,
        })

    return {"ok": True, "data": runs}


@router.get("/runs/{run_id}/files")
async def list_run_files(run_id: str, _user: dict = Depends(require_auth)):
    """List files in a specific business run."""
    run_dir = _safe_path(_BUSINESS_DIR, run_id)
    if not run_dir.is_dir():
        raise HTTPException(404, f"Run not found: {run_id}")

    files = []
    for f in sorted(run_dir.iterdir()):
        if not f.is_file():
            continue
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "extension": f.suffix,
            "is_text": f.suffix.lower() in _TEXT_EXTENSIONS,
            "modified_at": f.stat().st_mtime,
        })

    return {"ok": True, "data": files}


@router.get("/runs/{run_id}/files/{filename}")
async def read_artifact(
    run_id: str,
    filename: str,
    _user: dict = Depends(require_auth),
):
    """Read text content of an artifact file."""
    file_path = _safe_path(_BUSINESS_DIR, run_id, filename)
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {filename}")

    if file_path.suffix.lower() not in _TEXT_EXTENSIONS:
        raise HTTPException(
            400, "Cannot read binary file. Use /download endpoint."
        )

    try:
        content = file_path.read_text("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text")

    return {
        "ok": True,
        "data": {
            "name": filename,
            "run_id": run_id,
            "size": file_path.stat().st_size,
            "content": content,
        },
    }


@router.get("/runs/{run_id}/download/{filename}")
async def download_artifact(
    run_id: str,
    filename: str,
    _user: dict = Depends(require_auth),
):
    """Download a raw artifact file."""
    file_path = _safe_path(_BUSINESS_DIR, run_id, filename)
    if not file_path.is_file():
        raise HTTPException(404, f"File not found: {filename}")

    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )
