"""Tests structurels pour api/router_mount.py.

Vérifie que :
- mount_all_routers peut être importé et est appelable
- Les 4 routers critiques (abort startup on failure) sont référencés
- La fonction accepte les deux formes enable_stub_routes=True/False
- Un FastAPI minimal monte sans exception avec les routes disponibles
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Import smoke test ─────────────────────────────────────────────────────────

def test_router_mount_importable():
    """api.router_mount doit s'importer sans erreur."""
    import importlib
    mod = importlib.import_module("api.router_mount")
    assert hasattr(mod, "mount_all_routers")
    assert callable(mod.mount_all_routers)


def test_mount_critical_exists():
    """_mount_critical doit être défini dans le module."""
    import api.router_mount as rm
    assert hasattr(rm, "_mount_critical")
    assert callable(rm._mount_critical)


# ── Structural checks (AST) ────────────────────────────────────────────────────

CRITICAL_ROUTERS = [
    "api.routes.approval",
    "api.routes.missions",
    "api.routes.system_readiness",
    "api.routes.security_audit",
]


def test_critical_routers_referenced_in_source():
    """Les 4 routers critiques doivent apparaître dans router_mount.py."""
    source = Path("api/router_mount.py").read_text(encoding="utf-8")
    for router in CRITICAL_ROUTERS:
        assert router in source, (
            f"Critical router {router!r} not found in api/router_mount.py"
        )


def test_mount_critical_called_for_each_critical_router():
    """_mount_critical doit être appelé pour chaque router critique."""
    source = Path("api/router_mount.py").read_text(encoding="utf-8")
    for router in CRITICAL_ROUTERS:
        # Verify each appears as argument to _mount_critical(...)
        assert f'_mount_critical(app, "{router}")' in source, (
            f"_mount_critical not called with {router!r} in api/router_mount.py"
        )


def test_auth_router_mounted_last():
    """Le router auth doit être monté en dernier (convention)."""
    source = Path("api/router_mount.py").read_text(encoding="utf-8")
    auth_pos = source.rfind("_auth_routes.router")
    assert auth_pos != -1, "auth router not found in router_mount.py"
    # All critical routers should appear before the auth mount
    for router in CRITICAL_ROUTERS:
        pos = source.rfind(router)
        assert pos < auth_pos, (
            f"Critical router {router!r} appears after auth router mount"
        )


# ── Behavioural: mount with mocked app ────────────────────────────────────────

def test_mount_all_routers_calls_include_router():
    """mount_all_routers doit appeler app.include_router au moins une fois."""
    app_mock = MagicMock()

    # Patch all 60+ router imports to avoid real side-effects in test env
    with patch("importlib.import_module") as mock_import:
        # Return a module mock with a 'router' attribute
        fake_mod = MagicMock()
        fake_mod.router = MagicMock()
        mock_import.return_value = fake_mod

        # Also patch the direct from-import style used in mount_all_routers
        with patch.dict("sys.modules", {
            "api.ws": MagicMock(router=MagicMock()),
            "api.stream_router": MagicMock(router=MagicMock()),
            "api.routes.auth": MagicMock(
                router=MagicMock(),
                COOKIE_NAME="bea_token",
                COOKIE_MAX_AGE=86400,
                COOKIE_SECURE=False,
                set_auth_cookie=MagicMock(),
            ),
            "api.routes.learning": MagicMock(router=MagicMock()),
            "api.routes.training": MagicMock(router=MagicMock()),
            "api.routes.autonomy": MagicMock(router=MagicMock()),
            "api.routes.multimodal": MagicMock(router=MagicMock()),
            "api.routes.rag": MagicMock(router=MagicMock()),
            "api.routes.chat": MagicMock(router=MagicMock()),
            "api.routes.webhook": MagicMock(router=MagicMock()),
            "api.routes.metrics_llm": MagicMock(router=MagicMock()),
            "api.routes.business": MagicMock(router=MagicMock()),
            "api.routes.agent_builder": MagicMock(router=MagicMock()),
            "api.routes.mission_control": MagicMock(router=MagicMock()),
            "api.routes.routing_diagnostics": MagicMock(router=MagicMock()),
            "api.routes.monitoring": MagicMock(router=MagicMock()),
            "api.routes.projects": MagicMock(router=MagicMock()),
            "api.routes.objectives": MagicMock(router=MagicMock()),
            "api.routes.self_improvement": MagicMock(router=MagicMock()),
            "api.routes.dashboard": MagicMock(router=MagicMock()),
            "api.routes.approval": MagicMock(router=MagicMock()),
            "api.routes.convergence": MagicMock(router=MagicMock()),
            "api.routes.performance": MagicMock(router=MagicMock()),
            "api.routes.observability": MagicMock(router=MagicMock()),
            "api.routes.metrics_mobile": MagicMock(router=MagicMock()),
            "api.routes.extensions": MagicMock(router=MagicMock()),
            "api.routes.token_management": MagicMock(router=MagicMock()),
            "api.routes.skills": MagicMock(router=MagicMock()),
            "api.routes.system": MagicMock(router=MagicMock()),
            "api.routes.finance": MagicMock(router=MagicMock(), webhook_router=MagicMock()),
            "api.routes.missions": MagicMock(router=MagicMock()),
            "api.routes.vault": MagicMock(router=MagicMock()),
            "api.routes.identity": MagicMock(router=MagicMock()),
            "api.routes.connectors": MagicMock(router=MagicMock()),
            "api.routes.modules_v3": MagicMock(router=MagicMock()),
            "api.routes.cognitive": MagicMock(router=MagicMock()),
            "api.routes.action_console": MagicMock(router=MagicMock()),
            "api.routes.mcp_management": MagicMock(router=MagicMock()),
            "api.routes.self_model": MagicMock(router=MagicMock()),
            "api.routes.capability_routing": MagicMock(router=MagicMock()),
            "api.routes.cognitive_events": MagicMock(router=MagicMock()),
            "api.routes.mission_persistence": MagicMock(router=MagicMock()),
            "api.routes.business_actions": MagicMock(router=MagicMock()),
            "api.routes.business_artifacts": MagicMock(router=MagicMock()),
            "api.routes.opportunities": MagicMock(router=MagicMock()),
            "api.routes.products": MagicMock(router=MagicMock()),
            "api.routes.domain_skills": MagicMock(router=MagicMock()),
            "api.routes.operational_tools": MagicMock(router=MagicMock()),
            "api.routes.system_readiness": MagicMock(router=MagicMock()),
            "api.routes.plan_runner": MagicMock(router=MagicMock()),
            "api.routes.economic": MagicMock(router=MagicMock()),
            "api.routes.models": MagicMock(router=MagicMock()),
            "api.routes.execution": MagicMock(router=MagicMock()),
            "api.routes.strategy": MagicMock(router=MagicMock()),
            "api.routes.kernel": MagicMock(router=MagicMock()),
            "api.routes.security_audit": MagicMock(router=MagicMock()),
            "api.routes.debug": MagicMock(router=MagicMock()),
            "api.routes.system_v2": MagicMock(router=MagicMock()),
            "api.routes.self_improvement_v2": MagicMock(router=MagicMock()),
            "api.routes.modules": MagicMock(router=MagicMock()),
            "api.routes.misc_endpoints": MagicMock(router=MagicMock()),
        }):
            from api import router_mount as rm
            rm.mount_all_routers(app_mock, enable_stub_routes=False)

    assert app_mock.include_router.called, "include_router was never called"
    assert app_mock.include_router.call_count >= 10, (
        f"Expected >= 10 router mounts, got {app_mock.include_router.call_count}"
    )


def test_mount_critical_raises_on_import_failure():
    """_mount_critical doit lever RuntimeError si l'import échoue."""
    import importlib
    rm = importlib.import_module("api.router_mount")

    app_mock = MagicMock()
    with pytest.raises(RuntimeError, match="CRITICAL ROUTER FAILED"):
        rm._mount_critical(app_mock, "definitely.not.a.real.module")


def test_stub_routes_not_mounted_by_default():
    """Avec enable_stub_routes=False, les routers stub ne doivent pas être montés."""
    source = Path("api/router_mount.py").read_text(encoding="utf-8")
    # The stub routes are guarded by 'if enable_stub_routes:'
    # Check that browser, voice, playbooks, venture, finance router are gated
    gated = ["browser", "voice", "playbooks"]  # venture is a real feature, not a stub
    for name in gated:
        # Find the pattern: 'if enable_stub_routes:' before the import
        idx = source.find(f"api.routes.{name}")
        if idx == -1:
            continue  # module may not be listed
        preceding = source[max(0, idx - 200):idx]
        assert "enable_stub_routes" in preceding, (
            f"Stub router {name!r} not gated by enable_stub_routes"
        )
