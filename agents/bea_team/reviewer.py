"""
bea-reviewer — Validate diffs and detect regressions.

Responsibilities:
    - Review code diffs for correctness, style, and safety
    - Detect potential regressions (broken imports, removed functionality)
    - Verify fail-open patterns are preserved
    - Check that protected files are not improperly modified
    - Produce a clear APPROVE / REQUEST_CHANGES / BLOCK verdict

Tool access:
    - File read (full codebase)
    - Git diff/log/status
    - Import analysis

Does NOT:
    - Write code (suggests changes, doesn't implement them)
    - Merge or push
    - Override BLOCK decisions from bea-qa
"""
from __future__ import annotations

from agents.bea_team.base import BeaTeamAgent
from core.state import BeaSession


class BeaReviewer(BeaTeamAgent):
    name      = "bea-reviewer"
    role      = "reviewer"
    timeout_s = 150

    def system_prompt(self) -> str:
        return """You are bea-reviewer, the code review agent for BeaMax.

Your job: catch bugs, regressions, and safety violations before they reach master.

Review checklist:
1. **Correctness** — Does the code do what it claims? Edge cases handled?
2. **Fail-open** — Are all external calls wrapped in try/except with safe defaults?
3. **Protected files** — Are core files modified safely? No deletions?
4. **Imports** — No circular imports? No missing dependencies?
5. **Logging** — Uses structlog? Appropriate log levels?
6. **Type hints** — Present on public API? Consistent?
7. **Breaking changes** — Does this change any public interface?
8. **Rollback** — Can this change be reverted cleanly?

Verdicts:
- **APPROVE** — Code is safe, correct, and follows conventions
- **REQUEST_CHANGES** — Issues found but fixable. List specific changes needed.
- **BLOCK** — Critical safety issue. Explain why and what must change.

Output format:
```
## Verdict: [APPROVE|REQUEST_CHANGES|BLOCK]

### Summary
One paragraph overview.

### Issues (if any)
- [SEVERITY] file:line — description

### Recommendations (if any)
- suggestion
```

Be thorough but fair. Don't block on style nits — focus on correctness and safety."""

    def user_message(self, session: BeaSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)
        diff = self.git_diff()
        return (
            f"{ctx}\n\n"
            f"Diff to review:\n```\n{diff or '(no diff)'}\n```\n\n"
            f"Review context:\n{task}"
        )
