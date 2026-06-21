"""tests/test_api_v1_consolidation.py — PR #2: API v1/v3 consolidation tests.

Validates:
  - No duplicate method+path across v1.py and mission_control.py
  - Stream endpoint preserved at GET /api/v1/missions/{mission_id}/stream
  - core/observability is a proper package (no module/package conflict)
  - v1.py is the canonical facade for GET /api/v1/missions
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_V1_PY = _ROOT / "api" / "routes" / "v1.py"
_MC_PY = _ROOT / "api" / "routes" / "mission_control.py"
_OBS_PKG = _ROOT / "core" / "observability"


def _extract_routes(filepath: Path) -> list[tuple[str, str]]:
    """Extract (METHOD, path) pairs from a FastAPI router file via AST."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    routes: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        # Both sync `def` and async `async def` handlers
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


class TestV1RouteDuplication:
    def test_no_duplicate_method_path_between_v1_and_mission_control(self):
        """No (method, path) may appear in both v1.py and mission_control.py."""
        v1_routes = set(_extract_routes(_V1_PY))
        mc_routes = set(_extract_routes(_MC_PY))
        duplicates = v1_routes & mc_routes
        assert not duplicates, (
            f"Duplicate method+path across v1.py and mission_control.py: {sorted(duplicates)}. "
            "Remove duplicates from mission_control.py — v1.py is the canonical facade."
        )

    def test_stream_endpoint_preserved_in_mission_control(self):
        """GET .../stream must still be in mission_control.py — Flutter depends on it."""
        mc_routes = _extract_routes(_MC_PY)
        stream_routes = [(m, p) for m, p in mc_routes if "stream" in p]
        assert stream_routes, (
            "Stream endpoint missing from mission_control.py. "
            "GET /api/v1/missions/{mission_id}/stream is required by Flutter client."
        )

    def test_v1_canonical_list_missions(self):
        """GET /missions (list) must exist in v1.py — canonical v1 facade."""
        v1_routes = _extract_routes(_V1_PY)
        assert ("GET", "/missions") in v1_routes, (
            "GET /missions missing from api/routes/v1.py (canonical v1 facade)"
        )

    def test_mission_control_does_not_expose_list_missions(self):
        """mission_control.py must not define GET /missions (lives in v1.py)."""
        mc_routes = _extract_routes(_MC_PY)
        assert ("GET", "/missions") not in mc_routes, (
            "GET /missions in mission_control.py creates a duplicate with v1.py. "
            "The list endpoint belongs exclusively in api/routes/v1.py."
        )


class TestObservabilityPackage:
    def test_observability_is_package_not_module(self):
        """core/observability must be a package — a .py file would shadow the package."""
        obs_module = _ROOT / "core" / "observability.py"
        assert not obs_module.exists(), (
            "core/observability.py shadows the core/observability/ package — remove it."
        )
        assert _OBS_PKG.is_dir(), "core/observability/ package directory must exist"

    def test_observability_has_init_with_get_tracer(self):
        """core/observability/__init__.py must export get_tracer."""
        init = _OBS_PKG / "__init__.py"
        assert init.exists(), "core/observability/__init__.py is missing"
        source = init.read_text(encoding="utf-8")
        assert "get_tracer" in source, (
            "get_tracer not found in core/observability/__init__.py — "
            "'from core.observability import get_tracer' would break"
        )

    def test_observability_importable(self):
        """from core.observability import get_tracer must work without error."""
        from core.observability import get_tracer
        assert callable(get_tracer)
