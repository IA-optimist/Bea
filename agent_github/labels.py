"""
agent_github/labels.py — BEA_LABELS: canonical GitHub label definitions.

These labels must be created in the GitHub repo via:
    gh label create <name> --color <hex> --description <desc>
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GHLabel:
    name: str
    color: str   # 6-digit hex without #
    description: str


BEA_LABELS: tuple[GHLabel, ...] = (
    # Severity
    GHLabel("P0", "b60205", "Blocker — workflow stops"),
    GHLabel("P1", "e4e669", "Critical — must fix before next phase"),
    GHLabel("P2", "0e8a16", "Major — fix in sprint"),
    GHLabel("P3", "c5def5", "Minor / informational"),
    # Issue type
    GHLabel("bug", "d73a4a", "Confirmed bug"),
    GHLabel("enhancement", "a2eeef", "New feature or improvement"),
    GHLabel("question", "d876e3", "Question or clarification"),
    GHLabel("research", "bfd4f2", "Requires research before implementation"),
    GHLabel("security", "e11d48", "Security concern"),
    GHLabel("data", "7057ff", "Data agent / SQL scope"),
    GHLabel("self-improvement", "f9d0c4", "Controlled self-improvement request"),
    # Status
    GHLabel("human-review-required", "b60205", "Needs human review before proceeding"),
    GHLabel("pr-draft", "0075ca", "PR draft created — awaiting review"),
    GHLabel("needs-tests", "e4e669", "Implementation missing tests"),
    GHLabel("agentic", "5319e7", "Created by Béa agentic loop"),
)

LABEL_NAMES: frozenset[str] = frozenset(l.name for l in BEA_LABELS)
