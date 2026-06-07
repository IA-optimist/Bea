"""
BEA MAX — Bea Agent Team
================================
Meta-level agents that work ON the BeaMax codebase itself.

These are NOT mission-execution agents (scout-research, forge-builder, etc.).
These are system-building agents that improve, validate, and maintain BeaMax.

Agents:
    bea-architect  — system architecture decisions
    bea-coder      — implement code changes
    bea-reviewer   — validate diffs and detect regressions
    bea-qa         — create and run tests
    bea-devops     — deployment and environment validation
    bea-watcher    — monitor logs and detect anomalies

Constraints:
    - Agents work on separate branches
    - All changes reviewed before merge
    - No direct push to main
    - Fail-open philosophy preserved
"""
from agents.bea_team.architect import BeaArchitect
from agents.bea_team.coder import BeaCoder
from agents.bea_team.reviewer import BeaReviewer
from agents.bea_team.qa import BeaQA
from agents.bea_team.devops import BeaDevOps
from agents.bea_team.watcher import BeaWatcher

BEA_TEAM_AGENTS = {
    "bea-architect": BeaArchitect,
    "bea-coder":     BeaCoder,
    "bea-reviewer":  BeaReviewer,
    "bea-qa":        BeaQA,
    "bea-devops":    BeaDevOps,
    "bea-watcher":   BeaWatcher,
}

__all__ = [
    "BeaArchitect",
    "BeaCoder",
    "BeaReviewer",
    "BeaQA",
    "BeaDevOps",
    "BeaWatcher",
    "BEA_TEAM_AGENTS",
]
