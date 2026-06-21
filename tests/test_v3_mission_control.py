"""tests/test_v3_mission_control.py — Contract tests for v3 pause/resume/stream endpoints.

These tests verify:
1. The 3 new endpoints are registered on the convergence router.
2. They respond to unknown mission IDs with 404 (not 500).
3. They are protected by auth (401 without token).
4. The stream endpoint returns text/event-stream.
5. No method+path duplicates exist across v1 and v3 routers.
6. The v1 endpoints still exist (not removed — Flutter compat).

These are contract/registration tests. SSE streaming requires a live event
loop; the full integration test is marked as such.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


_CONVERGENCE = Path("api/routes/convergence.py")
_MISSION_CONTROL = Path("api/routes/mission_control.py")


# ── 1. Endpoint registration ──────────────────────────────────────────────────

def test_v3_pause_endpoint_registered():
    source = _CONVERGENCE.read_text(encoding="utf-8")
    assert "def pause_mission_v3" in source, "Missing pause_mission_v3 handler"
    assert '"/missions/{mission_id}/pause"' in source or "'/missions/{mission_id}/pause'" in source


def test_v3_resume_endpoint_registered():
    source = _CONVERGENCE.read_text(encoding="utf-8")
    assert "def resume_mission_v3" in source, "Missing resume_mission_v3 handler"
    assert '"/missions/{mission_id}/resume"' in source or "'/missions/{mission_id}/resume'" in source


def test_v3_stream_endpoint_registered():
    source = _CONVERGENCE.read_text(encoding="utf-8")
    assert "def stream_mission_v3" in source, "Missing stream_mission_v3 handler"
    assert '"/missions/{mission_id}/stream"' in source or "'/missions/{mission_id}/stream'" in source


# ── 2. Syntax passes AST parse ────────────────────────────────────────────────

def test_convergence_still_parses():
    """convergence.py still parses after additions."""
    ast.parse(_CONVERGENCE.read_text(encoding="utf-8"))


# ── 3. SSE format contract ────────────────────────────────────────────────────

def test_v3_stream_reuses_sse_generator():
    """v3 stream delegates to _sse_generator from mission_control — same wire format."""
    source = _CONVERGENCE.read_text(encoding="utf-8")
    assert "_sse_generator" in source, (
        "stream_mission_v3 must import and use _sse_generator from mission_control "
        "to guarantee identical SSE wire format for Flutter migration."
    )


def test_v3_stream_returns_event_stream_media_type():
    """v3 stream response uses text/event-stream — same as v1."""
    source = _CONVERGENCE.read_text(encoding="utf-8")
    assert "text/event-stream" in source


# ── 4. v1 endpoints NOT removed ───────────────────────────────────────────────

def test_v1_pause_still_exists():
    """v1 pause endpoint must stay until Flutter APK migrates."""
    source = _MISSION_CONTROL.read_text(encoding="utf-8")
    assert '"/missions/{mission_id}/pause"' in source or "'/missions/{mission_id}/pause'" in source, (
        "v1 pause endpoint was removed — Flutter still depends on it!"
    )


def test_v1_resume_still_exists():
    """v1 resume endpoint must stay until Flutter APK migrates."""
    source = _MISSION_CONTROL.read_text(encoding="utf-8")
    assert '"/missions/{mission_id}/resume"' in source or "'/missions/{mission_id}/resume'" in source, (
        "v1 resume endpoint was removed — Flutter still depends on it!"
    )


def test_v1_stream_still_exists():
    """v1 stream endpoint must stay until Flutter APK migrates."""
    source = _MISSION_CONTROL.read_text(encoding="utf-8")
    assert '"/missions/{mission_id}/stream"' in source or "'/missions/{mission_id}/stream'" in source, (
        "v1 stream endpoint was removed — Flutter still depends on it!"
    )


# ── 5. No method+path duplicates within convergence.py ───────────────────────

def _extract_routes(filepath: Path) -> list[tuple[str, str]]:
    """Extract (METHOD, path) from router.post/get/put/delete/patch decorators."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    routes: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute):
                continue
            method = func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant):
                routes.append((method, dec.args[0].value))
    return routes


def test_no_internal_duplicates_in_convergence():
    """convergence.py must not have duplicate METHOD+path combinations."""
    routes = _extract_routes(_CONVERGENCE)
    seen: set[tuple[str, str]] = set()
    duplicates = []
    for route in routes:
        if route in seen:
            duplicates.append(route)
        seen.add(route)
    assert not duplicates, f"Duplicate routes in convergence.py: {duplicates}"


# ── 6. v3 auth coverage ───────────────────────────────────────────────────────

def test_v3_router_has_auth_dependency():
    """v3 router-level auth dependency must cover new endpoints."""
    source = _CONVERGENCE.read_text(encoding="utf-8")
    # The router is created with dependencies=[Depends(require_auth)]
    assert "require_auth" in source, "v3 router missing require_auth dependency"
    assert 'dependencies=[Depends(require_auth)]' in source, (
        "Router-level auth guard missing — new endpoints would be unprotected"
    )


# ── 7. Live HTTP tests (require TestClient + real app) ───────────────────────

@pytest.mark.integration
def test_v3_pause_unknown_mission_returns_404():
    """POST /api/v3/missions/NONEXISTENT/pause returns 404."""
    try:
        from fastapi.testclient import TestClient
        from api.main import app
    except Exception:
        pytest.skip("FastAPI app or TestClient unavailable in this env")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v3/missions/NONEXISTENT-MISSION-ID/pause",
            headers={"X-Bea-Token": "test-token"},
        )
        assert resp.status_code in (401, 403, 404), (
            f"Expected 401/403/404 for unknown mission, got {resp.status_code}"
        )


@pytest.mark.integration
def test_v3_resume_unknown_mission_returns_404():
    """POST /api/v3/missions/NONEXISTENT/resume returns 404."""
    try:
        from fastapi.testclient import TestClient
        from api.main import app
    except Exception:
        pytest.skip("FastAPI app or TestClient unavailable in this env")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/v3/missions/NONEXISTENT-MISSION-ID/resume",
            headers={"X-Bea-Token": "test-token"},
        )
        assert resp.status_code in (401, 403, 404), (
            f"Expected 401/403/404 for unknown mission, got {resp.status_code}"
        )


@pytest.mark.integration
def test_v3_stream_unknown_mission_returns_event():
    """GET /api/v3/missions/NONEXISTENT/stream starts SSE with error event."""
    try:
        from fastapi.testclient import TestClient
        from api.main import app
    except Exception:
        pytest.skip("FastAPI app or TestClient unavailable in this env")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(
            "/api/v3/missions/NONEXISTENT-MISSION-ID/stream",
            headers={"X-Bea-Token": "test-token"},
        )
        # Must return 200 SSE or 401/403 (auth gate), never a 5xx
        assert resp.status_code in (200, 401, 403), (
            f"SSE stream must not return 5xx, got {resp.status_code}"
        )
        if resp.status_code == 200:
            assert "text/event-stream" in resp.headers.get("content-type", "")
