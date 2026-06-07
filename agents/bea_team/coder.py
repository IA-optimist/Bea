"""
bea-coder — Implement code changes.

Responsibilities:
    - Write Python code following BeaMax conventions
    - Produce clean diffs (minimal, focused changes)
    - Work on a dedicated branch (never on master)
    - Follow architectural guidance from bea-architect
    - Add docstrings, type hints, and structlog logging

Tool access:
    - File read/write
    - Git branch/commit/diff
    - Python syntax check (ast.parse)

Does NOT:
    - Push to main/master
    - Merge branches
    - Deploy anything
    - Delete protected files (core/meta_orchestrator.py, core/orchestrator.py, etc.)
"""
from __future__ import annotations

from agents.bea_team.base import BeaTeamAgent
from core.state import BeaSession


PROTECTED_FILES = frozenset({
    "core/meta_orchestrator.py",
    "core/orchestrator.py",
    "core/mission_system.py",
    "core/state.py",
    "core/contracts.py",
    "config/settings.py",
    "agents/crew.py",
})


class BeaCoder(BeaTeamAgent):
    name      = "bea-coder"
    role      = "builder"
    timeout_s = 240

    def system_prompt(self) -> str:
        return f"""You are bea-coder, the implementation agent for BeaMax.

Your job: write clean, correct Python code that follows the project's conventions.

Conventions:
- structlog for all logging (import structlog; log = structlog.get_logger())
- Type hints on all function signatures
- Docstrings on all public functions and classes
- Fail-open: wrap external calls in try/except, return safe defaults
- No bare except — always catch specific exceptions or use `except Exception`
- Imports: stdlib → third-party → local (separated by blank lines)

Branch discipline:
- ALWAYS work on a dedicated branch, never on master
- Branch naming: bea/<descriptive-name>
- Commits: concise, imperative mood ("Add X", "Fix Y", not "Added X")
- One logical change per commit

Protected files (NEVER delete, only modify with explicit approval):
{chr(10).join(f"  - {f}" for f in sorted(PROTECTED_FILES))}

Output format:
- Show the full diff (unified format) of your changes
- Explain what you changed and why
- Flag any concerns or risks

If the task is unclear, ask bea-architect for clarification rather than guessing."""

    def user_message(self, session: BeaSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)
        diff = self.git_diff()
        diff_block = f"\n\nCurrent diff vs master:\n```\n{diff}\n```" if diff else ""
        return f"{ctx}{diff_block}\n\nImplementation task:\n{task}"
