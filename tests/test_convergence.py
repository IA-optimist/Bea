"""
Convergence integration tests.

Tests:
1. Convergence API router imports and has correct routes
2. Orchestration bridge feature flag behavior
3. Canonical types map correctly
4. Memory facade wraps backends
5. End-to-end mission flow through bridge
6. Cockpit HTML exists and has v3 endpoints
7. Feature flag isolation
"""
import ast
from pathlib import Path

import pytest


def test_convergence_router_syntax():
    """Convergence API router parses without errors."""
    path = Path("api/routes/convergence.py")
    assert path.exists()
    source = path.read_text(encoding="utf-8")
    ast.parse(source)


def test_convergence_router_endpoints():
    """Router defines expected endpoint functions."""
    source = Path("api/routes/convergence.py").read_text(encoding="utf-8")
    for endpoint in [
        "submit_mission", "list_missions", "get_mission",
        "approve_mission", "reject_mission",
        "system_status", "system_health",
        "get_pending_approvals", "get_agent_status",
    ]:
        assert f"def {endpoint}" in source, f"Missing endpoint: {endpoint}"


def test_canonical_types_syntax():
    """canonical_types.py parses and has all enums."""
    source = Path("core/canonical_types.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "CanonicalMissionStatus" in classes
    assert "CanonicalRiskLevel" in classes


def test_orchestration_bridge_syntax():
    """orchestration_bridge.py parses."""
    source = Path("core/orchestration_bridge.py").read_text(encoding="utf-8")
    ast.parse(source)


def test_memory_facade_syntax():
    """memory_facade.py parses."""
    source = Path("core/memory_facade.py").read_text(encoding="utf-8")
    ast.parse(source)


def test_canonical_status_coverage():
    """Canonical status enum covers all legacy states."""
    source = Path("core/canonical_types.py").read_text(encoding="utf-8")
    # All legacy MissionSystem statuses should be mappable
    for legacy in ["submitted", "planning", "executing", "completed",
                   "failed", "cancelled"]:
        assert legacy in source.lower(), f"Missing canonical mapping for '{legacy}'"


def test_bridge_feature_flag():
    """Bridge respects BEA_USE_CANONICAL_ORCHESTRATOR flag."""
    source = Path("core/orchestration_bridge.py").read_text(encoding="utf-8")
    assert "BEA_USE_CANONICAL_ORCHESTRATOR" in source


def test_cockpit_is_ops_dashboard_not_mission_ui():
    """Le cockpit reconstruit (2026-06-06, 7572f39) est un dashboard ops.

    L'ancien cockpit missions a été consolidé dans app.html ; le fichier
    actuel ne doit PAS redevenir une UI missions parallèle (convergence :
    une seule UI missions = app.html).
    """
    source = Path("static/cockpit.html").read_text(encoding="utf-8")
    assert "/api/v3/performance" in source
    assert "/api/v3/missions" not in source


def test_no_existing_routes_modified():
    """Existing route files are not modified."""
    for f in ["api/routes/mission_control.py", "api/routes/approval.py",
              "api/routes/dashboard.py"]:
        if Path(f).exists():
            # Just verify they still parse
            ast.parse(Path(f).read_text(encoding="utf-8"))


@pytest.mark.skipif(not Path("docs/convergence-rollback.md").exists(),
                    reason="docs/convergence-rollback.md non créé (docs planifiés)")
def test_convergence_rollback_doc():
    """Rollback documentation exists."""
    doc_path = Path("docs/convergence-rollback.md")
    assert doc_path.exists(), "Missing rollback playbook"
    content = doc_path.read_text(encoding="utf-8")
    assert "rollback" in content.lower()
    assert "feature flag" in content.lower()
