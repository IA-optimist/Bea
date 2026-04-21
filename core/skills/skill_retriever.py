"""
core/skills/skill_retriever.py — Skill retrieval with lightweight scoring.

Finds relevant prior skills for a given mission goal.
Uses TF-IDF-like word overlap scoring (no heavy ML dependency).
Falls through to tag-based search if text similarity is weak.
"""
from __future__ import annotations

import re
import math
from collections import Counter

import structlog

from core.skills.skill_models import Skill
from core.skills.skill_registry import SkillRegistry

log = structlog.get_logger("skills.retriever")


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer — lowercase, alpha-only, 2+ chars."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 2]


def _cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two word-frequency counters."""
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    dot = sum(a[w] * b[w] for w in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class SkillRetriever:
    """
    Retrieves relevant skills for a mission goal.

    Scoring combines:
    - text similarity (cosine of word overlap)
    - confidence boost
    - use_count recency boost
    """

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.15,
        min_confidence: float = 0.3,
        tags: list[str] | None = None,
        problem_type: str = "",
    ) -> list[tuple[Skill, float]]:
        """
        Find relevant skills for a query.

        Returns list of (Skill, relevance_score) sorted by score desc.
        Only returns skills above min_score and min_confidence.
        """
        query_tokens = Counter(_tokenize(query))
        if not query_tokens:
            return []

        candidates: list[tuple[Skill, float]] = []

        for skill in self._registry.all():
            # Skip low-confidence skills
            if skill.confidence < min_confidence:
                continue

            # Tag filter if specified
            if tags:
                tag_set = set(t.lower() for t in tags)
                skill_tags = set(t.lower() for t in skill.tags)
                if not (tag_set & skill_tags):
                    continue

            # Compute text similarity
            skill_tokens = Counter(_tokenize(skill.text_for_search()))
            sim = _cosine_similarity(query_tokens, skill_tokens)

            # Confidence boost (up to +0.1)
            score = sim + (skill.confidence * 0.1)

            # Use count recency boost (diminishing, up to +0.05)
            if skill.use_count > 0:
                score += min(0.05, skill.use_count * 0.01)

            # Problem type matching boost (+0.15 if same type)
            if problem_type and skill.problem_type:
                if skill.problem_type.lower() == problem_type.lower():
                    score += 0.15

            if score >= min_score:
                candidates.append((skill, round(score, 4)))

        candidates.sort(key=lambda x: -x[1])
        result = candidates[:top_k]

        if result:
            log.info("skills_retrieved",
                     query=query[:60],
                     count=len(result),
                     top_score=result[0][1],
                     top_skill=result[0][0].name)
        else:
            log.debug("skills_no_match", query=query[:60])

        return result

    def retrieve_for_planning(
        self,
        goal: str,
        top_k: int = 3,
        min_score: float = 0.15,
    ) -> list[dict]:
        """
        Retrieve skills formatted for injection into planning context.

        Returns list of dicts with name, description, steps, confidence.
        Ready to be included in LLM planning prompts.
        """
        results = self.retrieve(goal, top_k=top_k, min_score=min_score)
        return [
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "problem_type": skill.problem_type,
                "steps": [s.description for s in skill.steps],
                "tools_used": skill.tools_used,
                "confidence": skill.confidence,
                "use_count": skill.use_count,
            }
            for skill, _score in results
        ]
