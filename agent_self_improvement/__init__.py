"""
agent_self_improvement — Controlled self-improvement (MemGPT/Voyager pattern).

ABSOLUTE INVARIANTS (never bypass):
  1. No direct patching of the codebase from this module.
  2. Self-improvement requests CREATE a GitHub issue, then the GitHub
     Mission Loop handles the rest via human review.
  3. Security improvements ALWAYS require human_approval=True.
  4. Skill library: skills require tests + source, never auto-deployed.
  5. Kernel gate from kernel/improvement/gate.py is consulted for all
     improvement cycles.

Public surface:
    from agent_self_improvement import Skill, SkillLibrary
    from agent_self_improvement import ImprovementIssue, ReflectionAgent
"""
from __future__ import annotations

from agent_self_improvement.skill_library import Skill, SkillLibrary
from agent_self_improvement.improvement_issues import ImprovementIssue, ImprovementKind
from agent_self_improvement.reflection import ReflectionAgent

__all__ = [
    "Skill",
    "SkillLibrary",
    "ImprovementIssue",
    "ImprovementKind",
    "ReflectionAgent",
]
