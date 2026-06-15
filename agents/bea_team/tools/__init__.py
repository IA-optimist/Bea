"""
agents/bea_team/tools — Tool access layer for bea-team agents.

Backward-compatible re-export package. All names previously importable from
`agents.bea_team.tools` continue to work through this `__init__.py`.

Internal layout:
  _base.py         — ToolRisk, ToolResult, _timed, REPO_ROOT, is_protected
  _git.py          — tool_git_* functions
  _files.py        — tool_read_file, tool_write_file, tool_patch_file, …
  _analysis.py     — tool_syntax_validate, tool_import_graph, …
  _testing.py      — tool_run_tests, tool_run_single_test, …
  _diff.py         — tool_generate_diff, tool_diff_summary
  _observability.py— tool_read_logs, tool_detect_error_patterns, tool_detect_regressions
  _env.py          — tool_python_version, tool_detect_docker_config, …
  _knowledge.py    — tool_store_pattern, tool_search_patterns, …
  _coordination.py — tool_create_task, tool_report_status
  _registry.py     — AGENT_TOOL_ACCESS, TOOL_CATALOG
"""
from __future__ import annotations

# ── Shared types ──────────────────────────────────────────────────────────────
from ._base import (
    ToolRisk,
    ToolResult,
    _timed,
    REPO_ROOT,
    PROTECTED_FILES,
    PROTECTED_DIRS,
    is_protected,
)

# ── Section imports ───────────────────────────────────────────────────────────
from ._git import (
    _git,
    tool_git_branch_create,
    tool_git_status,
    tool_git_diff,
    tool_git_log,
    tool_git_commit,
    tool_git_compare_branches,
    tool_git_detect_conflicts,
)
from ._files import (
    tool_read_file,
    tool_write_file,
    tool_patch_file,
    tool_list_directory,
    tool_detect_file_dependencies,
)
from ._analysis import (
    tool_syntax_validate,
    tool_import_graph,
    tool_circular_import_detect,
    tool_dead_code_detect,
    tool_complexity_estimate,
)
from ._testing import (
    tool_run_tests,
    tool_run_single_test,
    tool_detect_missing_tests,
)
from ._diff import (
    tool_generate_diff,
    tool_diff_summary,
)
from ._observability import (
    tool_read_logs,
    tool_detect_error_patterns,
    tool_detect_regressions,
)
from ._env import (
    tool_python_version,
    tool_detect_installed_packages,
    tool_detect_missing_dependencies,
    tool_detect_docker_config,
    tool_env_vars_check,
)
from ._knowledge import (
    tool_store_pattern,
    tool_search_patterns,
    tool_store_decision,
)
from ._coordination import (
    tool_create_task,
    tool_report_status,
)
from ._registry import AGENT_TOOL_ACCESS, TOOL_CATALOG


def get_tools_for_agent(agent_name: str) -> dict[str, callable]:
    """
    Returns the tools an agent is allowed to use.
    Fail-open: unknown agent gets read-only tools.
    """
    allowed = AGENT_TOOL_ACCESS.get(agent_name, {
        "tool_read_file", "tool_list_directory", "tool_git_status",
    })
    # All tool functions are imported into this module's namespace.
    module_globals = globals()
    return {
        name: module_globals[name]
        for name in allowed
        if name in module_globals and callable(module_globals[name])
    }


__all__ = [
    # Types
    "ToolRisk", "ToolResult", "_timed", "REPO_ROOT",
    "PROTECTED_FILES", "PROTECTED_DIRS", "is_protected",
    # Git
    "_git",
    "tool_git_branch_create", "tool_git_status", "tool_git_diff",
    "tool_git_log", "tool_git_commit", "tool_git_compare_branches",
    "tool_git_detect_conflicts",
    # Files
    "tool_read_file", "tool_write_file", "tool_patch_file",
    "tool_list_directory", "tool_detect_file_dependencies",
    # Analysis
    "tool_syntax_validate", "tool_import_graph", "tool_circular_import_detect",
    "tool_dead_code_detect", "tool_complexity_estimate",
    # Testing
    "tool_run_tests", "tool_run_single_test", "tool_detect_missing_tests",
    # Diff
    "tool_generate_diff", "tool_diff_summary",
    # Observability
    "tool_read_logs", "tool_detect_error_patterns", "tool_detect_regressions",
    # Env
    "tool_python_version", "tool_detect_installed_packages",
    "tool_detect_missing_dependencies", "tool_detect_docker_config",
    "tool_env_vars_check",
    # Knowledge
    "tool_store_pattern", "tool_search_patterns", "tool_store_decision",
    # Coordination
    "tool_create_task", "tool_report_status",
    # Registry
    "AGENT_TOOL_ACCESS", "TOOL_CATALOG", "get_tools_for_agent",
]
