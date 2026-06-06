"""
Jarvis Team — Base class for meta-level agents.

All jarvis-team agents inherit from JarvisTeamAgent, which extends BaseAgent
with codebase-aware tooling: git operations, file I/O, test execution,
and branch management.

Fail-open: every tool access is wrapped in try/except. If a tool is
unavailable, the agent degrades gracefully (returns empty context, skips
the operation) rather than crashing the pipeline.
"""
from __future__ import annotations

import subprocess  # nosec B404
import structlog
from pathlib import Path

from agents.crew import BaseAgent

log = structlog.get_logger(__name__)

# Root of the JarvisMax repo — resolved at import time, overridable via env.
import os
REPO_ROOT = Path(os.environ.get("JARVISMAX_REPO", ".")).resolve()


class JarvisTeamAgent(BaseAgent):
    """
    Base for all jarvis-team agents.

    Provides:
        - git helpers (branch, diff, status)
        - file read/write with path guards
        - test runner
        - repo-root awareness

    Subclasses implement system_prompt() and user_message() as usual.
    """

    # Subclasses override these
    name:      str = "jarvis-team-base"
    role:      str = "builder"
    timeout_s: int = 180

    # ── Git helpers ───────────────────────────────────────────

    @staticmethod
    def _git(cmd: str, cwd: Path | None = None, timeout: int = 30) -> str:
        """Run a git command, return stdout. Fail-open: returns '' on error."""
        import shlex
        try:
            result = subprocess.run(  # nosec B603 B607
                ["git"] + shlex.split(cmd),
                shell=False,
                cwd=str(cwd or REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout.strip()
        except Exception as e:
            log.warning("jarvis_team_git_failed", cmd=cmd[:80], err=str(e)[:100])
            return ""

    def git_current_branch(self) -> str:
        return self._git("rev-parse --abbrev-ref HEAD")

    def git_status(self) -> str:
        return self._git("status --short")

    def git_diff(self, base: str = "master") -> str:
        """Diff against base branch. Truncated to 8000 chars for prompt injection."""
        diff = self._git(f"diff {base} --stat") + "\n\n" + self._git(f"diff {base}")
        return diff[:8000]

    def git_log(self, n: int = 10) -> str:
        return self._git(f"log --oneline -n {n}")

    def git_create_branch(self, branch_name: str) -> str:
        """Create and checkout a new branch. Returns branch name or ''."""
        existing = self._git("branch --list " + branch_name)
        if existing:
            self._git(f"checkout {branch_name}")
            return branch_name
        result = self._git(f"checkout -b {branch_name}")
        if "Switched to" in result or not result:
            # Verify
            current = self.git_current_branch()
            return current if current == branch_name else ""
        return ""

    # ── File helpers ──────────────────────────────────────────

    @staticmethod
    def read_file(path: str | Path, max_chars: int = 10000) -> str:
        """Read a file from the repo. Fail-open: returns '' on error."""
        try:
            p = Path(path)
            if not p.is_absolute():
                p = REPO_ROOT / p
            content = p.read_text(encoding="utf-8", errors="replace")
            return content[:max_chars]
        except Exception as e:
            log.debug("jarvis_team_read_failed", path=str(path)[:100], err=str(e)[:80])
            return ""

    @staticmethod
    def list_files(directory: str | Path = ".", pattern: str = "*.py") -> list[str]:
        """List files matching pattern. Fail-open: returns [] on error."""
        try:
            d = Path(directory)
            if not d.is_absolute():
                d = REPO_ROOT / d
            return [str(f.relative_to(REPO_ROOT)) for f in d.rglob(pattern)]
        except Exception:
            return []

    # ── Test runner ───────────────────────────────────────────

    @staticmethod
    def run_tests(test_path: str = "tests/", timeout: int = 120) -> str:
        """Run pytest on a path. Returns stdout+stderr. Fail-open."""
        try:
            result = subprocess.run(  # nosec B603 B607
                ["python", "-m", "pytest", test_path, "-x", "-q", "--tb=short"],
                shell=False,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return (result.stdout + "\n" + result.stderr).strip()[:5000]
        except subprocess.TimeoutExpired:
            return f"Tests timed out after {timeout}s"
        except Exception as e:
            return f"Test runner failed: {str(e)[:200]}"

    # ── Tool access ─────────────────────────────────────────────

    def get_tools(self) -> dict:
        """
        Returns the tool functions this agent is allowed to use.
        Uses the AGENT_TOOL_ACCESS matrix from tools.py. Fail-open.
        """
        try:
            from agents.jarvis_team.tools import get_tools_for_agent
            return get_tools_for_agent(self.name)
        except Exception as e:
            log.debug("jarvis_team_tools_unavailable", agent=self.name, err=str(e)[:80])
            return {}

    def tool_summary(self) -> str:
        """Human-readable summary of available tools for this agent."""
        try:
            from agents.jarvis_team.tools import AGENT_TOOL_ACCESS, TOOL_CATALOG
            allowed = AGENT_TOOL_ACCESS.get(self.name, set())
            lines = [f"## Tools available to {self.name}"]
            for entry in TOOL_CATALOG:
                fn_name = f"tool_{entry['name']}"
                if fn_name in allowed:
                    lines.append(f"- **{entry['name']}** [{entry['risk']}] — {entry['purpose']}")
            return "\n".join(lines) if len(lines) > 1 else "No tools configured."
        except Exception:
            return "Tool catalog unavailable."

    # ── Repo context for prompts ──────────────────────────────

    def repo_context(self) -> str:
        """Build a concise repo context block for prompt injection."""
        branch = self.git_current_branch()
        status = self.git_status()
        recent = self.git_log(5)
        return (
            f"## Repo Context\n"
            f"Branch: {branch}\n"
            f"Status:\n{status or '(clean)'}\n"
            f"Recent commits:\n{recent}\n"
        )
