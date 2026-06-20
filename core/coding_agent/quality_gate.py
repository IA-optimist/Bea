"""Deterministic quality-gate planning for Bea coding agents.

The goal is to make a coding agent choose verification commands from the
actual files it changed instead of relying on a generic "run tests" step.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PYTHON_DIRS = ("api/", "agents/", "core/", "executor/", "memory/", "tools/")
FRONTEND_DIRS = ("frontend/", "mobile/")
FRONTEND_EXTENSIONS = {".css", ".html", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
DOCKER_FILES = {"docker-compose.yml", "docker-compose.override.yml", "Dockerfile", "Caddyfile"}
SECURITY_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}


@dataclass(frozen=True)
class QualityGateCommand:
    """A command the agent must run or justify skipping."""

    name: str
    command: list[str]
    cwd: str = "."
    required: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityGatePlan:
    """Verification plan derived from changed files."""

    changed_files: list[str]
    commands: list[QualityGateCommand]
    risk_level: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["commands"] = [cmd.to_dict() for cmd in self.commands]
        return data


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _is_python_source(path: str) -> bool:
    return path.endswith(".py") and path.startswith(PYTHON_DIRS)


def _is_python_test(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py")


def _is_frontend(path: str) -> bool:
    p = Path(path)
    return path.startswith(FRONTEND_DIRS) and (
        p.suffix in FRONTEND_EXTENSIONS or p.name in SECURITY_FILES
    )


def _is_docker(path: str) -> bool:
    p = Path(path)
    return p.name in DOCKER_FILES or path.startswith(".docker/")


def _is_security_sensitive(path: str) -> bool:
    return Path(path).name in SECURITY_FILES or path.startswith(("auth/", "api/auth", "security/"))


def _risk_level(files: list[str]) -> str:
    if any(_is_docker(f) for f in files):
        return "high"
    if any(_is_security_sensitive(f) for f in files):
        return "high"
    if any(_is_python_source(f) or _is_frontend(f) for f in files):
        return "medium"
    return "low"


def build_quality_gate_plan(changed_files: list[str]) -> QualityGatePlan:
    """Build the minimal verification plan for a set of changed files."""
    files = sorted({_normalize(f) for f in changed_files if str(f).strip()})
    commands: list[QualityGateCommand] = []
    names: set[str] = set()

    def add(cmd: QualityGateCommand) -> None:
        if cmd.name not in names:
            names.add(cmd.name)
            commands.append(cmd)

    has_python = any(_is_python_source(f) or _is_python_test(f) for f in files)
    has_frontend = any(_is_frontend(f) for f in files)
    has_docker = any(_is_docker(f) for f in files)
    has_security = any(_is_security_sensitive(f) for f in files)

    if has_python:
        add(QualityGateCommand(
            name="python_lint",
            command=["ruff", "check", "."],
            reason="Python changes require static checks before delivery.",
        ))
        test_files = [f for f in files if _is_python_test(f)]
        if test_files:
            add(QualityGateCommand(
                name="python_targeted_tests",
                command=["python", "-m", "pytest", *test_files, "-q"],
                reason="Changed tests must be executed directly.",
            ))
        add(QualityGateCommand(
            name="python_regression_tests",
            command=["python", "-m", "pytest", "tests", "-q", "-m", "not integration"],
            reason="Python source changes need the non-integration regression suite.",
        ))

    if has_frontend:
        add(QualityGateCommand(
            name="frontend_build",
            command=["npm", "run", "build"],
            cwd="frontend",
            reason="Frontend changes must compile the production bundle.",
        ))
        add(QualityGateCommand(
            name="frontend_e2e",
            command=["npm", "run", "test:e2e"],
            cwd="frontend",
            reason="UI changes require browser-flow coverage.",
        ))

    if has_docker:
        add(QualityGateCommand(
            name="docker_compose_config",
            command=["docker", "compose", "-f", "docker-compose.yml", "config"],
            reason="Docker and proxy changes must render to a valid compose model.",
        ))

    if has_security:
        add(QualityGateCommand(
            name="security_audit",
            command=["python", "scripts/validate_local.py"],
            reason="Dependency or auth/security changes require the security delta gate.",
        ))

    risk = _risk_level(files)
    score = 1.0
    if risk == "high":
        score = 0.95 if len(commands) >= 2 else 0.75
    elif risk == "medium":
        score = 0.9 if commands else 0.65

    return QualityGatePlan(
        changed_files=files,
        commands=commands,
        risk_level=risk,
        score=score,
    )
