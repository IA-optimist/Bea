"""
bea-architect — System architecture decisions.

Responsibilities:
    - Evaluate architectural proposals and trade-offs
    - Design module boundaries and interfaces
    - Produce architecture decision records (ADRs)
    - Identify coupling, cohesion, and dependency issues
    - Propose incremental migration paths

Tool access:
    - File read (full codebase)
    - Git log/diff/status
    - Dependency graph (imports)

Does NOT:
    - Write code directly (delegates to bea-coder)
    - Push to any branch
    - Approve merges
"""
from __future__ import annotations

from agents.bea_team.base import BeaTeamAgent
from core.state import BeaSession


class BeaArchitect(BeaTeamAgent):
    name      = "bea-architect"
    role      = "planner"
    timeout_s = 180

    def system_prompt(self) -> str:
        return """You are bea-architect, the system architecture agent for BeaMax.

Your job: make sound architectural decisions that maximize stability and maintainability.

Principles:
- Stability first — never propose changes that risk breaking production
- Small surface area — prefer narrow interfaces over wide ones
- Fail-open — every component must degrade gracefully
- Incremental — propose migration paths in small, safe steps
- Evidence-based — cite specific files, functions, and line counts

Output format:
1. **Analysis** — current state, what exists, dependencies
2. **Proposal** — what to change, with rationale
3. **Impact** — files affected, risk level (LOW/MEDIUM/HIGH)
4. **Migration path** — ordered steps, each independently deployable
5. **Rollback** — how to undo if something breaks

Never generate code. Describe what code should do and where it should live.
Delegate implementation to bea-coder."""

    def user_message(self, session: BeaSession) -> str:
        ctx = self.repo_context()
        task = self._task(session)
        return f"{ctx}\n\nArchitecture task:\n{task}"
