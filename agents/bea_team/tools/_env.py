"""Environment inspection tools for bea-team agents."""
from __future__ import annotations

import os
import subprocess  # nosec B404
from pathlib import Path

from ._base import REPO_ROOT, ToolResult, _timed


@_timed
def tool_python_version() -> ToolResult:
    """Detect Python version."""
    import sys
    return ToolResult(
        success=True, tool="python_version",
        data={
            "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "full": sys.version,
        },
    )


@_timed
def tool_detect_installed_packages() -> ToolResult:
    """List installed Python packages."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["python3", "-m", "pip", "list", "--format=json"],
            shell=False, capture_output=True, text=True, timeout=15,
        )
        import json as _json
        try:
            packages = _json.loads(result.stdout)
        except Exception:
            packages = []
        return ToolResult(
            success=True, tool="detect_installed_packages",
            data={"packages": packages, "count": len(packages)},
        )
    except Exception as e:
        return ToolResult(success=False, tool="detect_installed_packages", error=str(e)[:300])


@_timed
def tool_detect_missing_dependencies() -> ToolResult:
    """Compare imports in codebase against installed packages."""
    from ._analysis import tool_import_graph
    graph_result = tool_import_graph()
    if not graph_result.success:
        return graph_result
    all_imports: set[str] = set()
    for deps in graph_result.data.get("graph", {}).values():
        for d in deps:
            all_imports.add(d.split(".")[0])
    missing = []
    for mod in all_imports:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return ToolResult(
        success=True, tool="detect_missing_dependencies",
        data={"missing": missing, "checked": len(all_imports)},
    )


@_timed
def tool_detect_docker_config() -> ToolResult:
    """Inspect docker-compose configuration."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    prod_path = REPO_ROOT / "docker-compose.prod.yml"
    data: dict = {"files": []}
    for p in [compose_path, prod_path]:
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            data["files"].append({
                "path": str(p.relative_to(REPO_ROOT)),
                "content": content[:5000],
                "lines": content.count("\n") + 1,
            })
    return ToolResult(success=True, tool="detect_docker_config", data=data)


@_timed
def tool_env_vars_check() -> ToolResult:
    """Check which expected environment variables are set (names only, not values)."""
    expected = [
        "BEA_ROOT", "BEAMAX_REPO", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "DATABASE_URL", "REDIS_URL", "QDRANT_URL",
        "OLLAMA_HOST", "GITHUB_TOKEN",
    ]
    status = {}
    for var in expected:
        val = os.environ.get(var, "")
        status[var] = "SET" if val else "MISSING"
    return ToolResult(
        success=True, tool="env_vars_check",
        data={"vars": status, "set_count": sum(1 for v in status.values() if v == "SET")},
    )
