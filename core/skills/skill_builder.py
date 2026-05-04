"""
core/skills/skill_builder.py — Builds skills from successful mission results.

Applies creation criteria to avoid noisy proliferation:
- mission must have succeeded
- result must be non-trivial
- must not duplicate an existing skill
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

import structlog

from core.skills.skill_models import Skill, SkillStep
from core.skills.skill_registry import SkillRegistry
from core.skills.skill_retriever import _tokenize, _cosine_similarity

log = structlog.get_logger("skills.builder")

# Minimum thresholds for skill creation
_MIN_RESULT_LENGTH = 80          # chars — skip trivial one-liners
_MIN_GOAL_LENGTH = 10            # chars — skip empty goals
_DUPLICATE_THRESHOLD = 0.75      # cosine similarity above this = duplicate
_MIN_CONFIDENCE_TO_STORE = 0.4   # don't store low-confidence skills


class SkillBuilder:
    """
    Evaluates mission outcomes and builds reusable skills when warranted.

    Handles duplicate detection and skill merging.
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def maybe_create(
        self,
        mission_id: str,
        goal: str,
        result: str,
        status: str,
        tools_used: list[str] | None = None,
        agents_used: list[str] | None = None,
        steps_taken: list[str] | None = None,
        risk_level: str = "low",
        confidence: float = 0.6,
    ) -> Optional[Skill]:
        """
        Evaluate whether a mission result warrants a new skill.

        Returns the created/updated Skill, or None if not warranted.
        """
        tools_used = tools_used or []
        agents_used = agents_used or []
        steps_taken = steps_taken or []

        # ── Gate checks ──────────────────────────────────────────

        if status not in ("DONE", "done", "success"):
            log.debug("skill_skip_not_done", mission_id=mission_id, status=status)
            return None

        if len(goal) < _MIN_GOAL_LENGTH:
            log.debug("skill_skip_trivial_goal", mission_id=mission_id)
            return None

        if len(result) < _MIN_RESULT_LENGTH:
            log.debug("skill_skip_trivial_result",
                      mission_id=mission_id, result_len=len(result))
            return None

        if confidence < _MIN_CONFIDENCE_TO_STORE:
            log.debug("skill_skip_low_confidence",
                      mission_id=mission_id, confidence=confidence)
            return None

        # ── Duplicate check ──────────────────────────────────────

        existing = self._find_duplicate(goal)
        if existing:
            # Update existing skill instead of creating new one
            self._merge_into(existing, result, tools_used, confidence)
            return existing

        # ── Build the skill ──────────────────────────────────────

        name = self._derive_name(goal)
        problem_type = self._classify_problem(goal, tools_used)
        tags = self._extract_tags(goal, result, tools_used)
        steps = [
            SkillStep(order=i + 1, description=s)
            for i, s in enumerate(steps_taken)
        ] if steps_taken else self._infer_steps(result)

        skill = Skill(
            name=name,
            description=goal,
            problem_type=problem_type,
            context=f"Learned from mission {mission_id}",
            tools_used=tools_used,
            steps=steps,
            tags=tags,
            confidence=confidence,
            risk_level=risk_level,
            source_mission_id=mission_id,
        )

        self._registry.add(skill)
        return skill

    # ── Duplicate detection ──────────────────────────────────────

    def _find_duplicate(self, candidate_text: str) -> Optional[Skill]:
        """Check if a similar skill already exists."""
        candidate_tokens = Counter(_tokenize(candidate_text))
        if not candidate_tokens:
            return None

        for skill in self._registry.all():
            # Compare against name + description (the core identity)
            existing_text = f"{skill.name} {skill.description}"
            existing_tokens = Counter(_tokenize(existing_text))
            sim = _cosine_similarity(candidate_tokens, existing_tokens)
            if sim >= _DUPLICATE_THRESHOLD:
                log.info("skill_duplicate_detected",
                         existing=skill.skill_id, similarity=round(sim, 3))
                return skill
        return None

    def _merge_into(
        self, skill: Skill, new_result: str,
        tools: list[str], confidence: float
    ) -> None:
        """Merge new information into an existing skill."""
        # Update confidence (weighted average)
        skill.confidence = round(
            (skill.confidence * skill.use_count + confidence) / (skill.use_count + 1),
            3
        )
        # Add new tools
        for t in tools:
            if t not in skill.tools_used:
                skill.tools_used.append(t)
        skill.use_count += 1
        self._registry.update(skill)
        log.info("skill_merged", id=skill.skill_id, new_confidence=skill.confidence)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _derive_name(goal: str) -> str:
        """Create a short skill name from goal text."""
        clean = goal.strip()[:60]
        # Remove trailing punctuation
        clean = re.sub(r"[.!?]+$", "", clean)
        return clean

    @staticmethod
    def _classify_problem(goal: str, tools: list[str]) -> str:
        """Simple heuristic problem classification."""
        g = goal.lower()
        if any(w in g for w in ["deploy", "docker", "server", "nginx"]):
            return "deployment"
        if any(w in g for w in ["fix", "bug", "error", "crash", "debug"]):
            return "debugging"
        if any(w in g for w in ["test", "pytest", "unittest"]):
            return "testing"
        if any(w in g for w in ["api", "endpoint", "route", "http"]):
            return "api_work"
        if any(w in g for w in ["analyze", "analyse", "review", "audit"]):
            return "analysis"
        if any(w in g for w in ["write", "create", "build", "implement"]):
            return "implementation"
        if any(w in g for w in ["search", "find", "look", "research"]):
            return "research"
        if any(t in ["shell", "terminal"] for t in tools):
            return "system_ops"
        return "general"

    @staticmethod
    def _extract_tags(goal: str, result: str, tools: list[str]) -> list[str]:
        """Extract meaningful tags from goal and result."""
        tags = list(set(tools))  # tools as tags
        # Extract tech keywords
        combined = f"{goal} {result}".lower()
        tech_terms = [
            "python", "docker", "api", "database", "git", "nginx",
            "fastapi", "react", "flutter", "postgres", "redis",
            "test", "deploy", "debug", "security", "performance",
        ]
        for term in tech_terms:
            if term in combined and term not in tags:
                tags.append(term)
        return tags[:10]  # cap at 10 tags

    @staticmethod
    def _infer_steps(result: str) -> list[SkillStep]:
        """Try to extract steps from result text (numbered lists, etc.)."""
        steps = []
        # Look for numbered patterns: "1. ...", "1) ...", "Step 1: ..."
        pattern = re.compile(r"(?:^|\n)\s*(?:\d+[.)]\s*|[Ss]tep\s*\d+[.:]\s*)(.*?)(?=\n|$)")
        for i, match in enumerate(pattern.finditer(result)):
            desc = match.group(1).strip()
            if desc and len(desc) > 5:
                steps.append(SkillStep(order=i + 1, description=desc))
        return steps[:10]  # cap
