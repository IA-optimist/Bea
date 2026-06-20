from __future__ import annotations

from core.coding_agent.quality_gate import build_quality_gate_plan


def _names(files: list[str]) -> set[str]:
    return {cmd.name for cmd in build_quality_gate_plan(files).commands}


def test_python_changes_require_lint_and_regression_tests():
    plan = build_quality_gate_plan(["core/memory_facade.py"])

    assert plan.risk_level == "medium"
    assert {"python_lint", "python_regression_tests"} <= {cmd.name for cmd in plan.commands}
    assert plan.score >= 0.9


def test_changed_python_tests_run_directly():
    names = _names(["tests/test_memory_facade.py"])

    assert "python_targeted_tests" in names
    assert "python_regression_tests" in names


def test_frontend_changes_require_build_and_e2e():
    names = _names(["frontend/src/App.tsx", "frontend/package.json"])

    assert {"frontend_build", "frontend_e2e"} <= names


def test_docker_changes_are_high_risk_and_validate_compose():
    plan = build_quality_gate_plan(["docker-compose.yml", "Caddyfile"])

    assert plan.risk_level == "high"
    assert "docker_compose_config" in {cmd.name for cmd in plan.commands}


def test_dependency_changes_add_security_gate():
    names = _names(["requirements.txt"])

    assert "security_audit" in names
