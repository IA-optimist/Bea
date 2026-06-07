"""
BEA MAX — Hierarchical Planner
==================================
Adds a strategic decomposition layer on top of MissionPlanner.

Architecture:
  HierarchicalPlan
    └── MacroGoal[0]  (strategic objective)
          └── MissionPlan  (tactical steps via MissionPlanner)
    └── MacroGoal[1]
          └── MissionPlan
    └── MacroGoal[2]  (optional)
          └── MissionPlan

Activation:
  - Only triggers for goals with complexity == "high" AND goal length > 80 chars.
  - Falls back to flat MissionPlanner if decomposition produces < 2 macro-goals.

Design rules:
  - No LLM call for decomposition (keyword pattern matching, same approach as MissionPlanner).
  - Fail-open: if hierarchical planner fails, caller should use flat MissionPlanner.
  - In-memory only (no persistence) — plans are ephemeral per-mission.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_MACRO_GOALS = 3
MIN_MACRO_GOALS = 2
HIERARCHICAL_MIN_GOAL_LEN = 60  # chars — short goals don't need hierarchy


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class MacroGoal:
    """A single strategic objective with its tactical plan."""
    macro_id: int
    description: str               # Strategic objective description
    mission_type: str              # Taxonomy type of this objective
    estimated_complexity: str      # "low" | "medium" | "high"
    tactical_plan: object | None = None   # MissionPlan from MissionPlanner
    status: str = "pending"        # "pending" | "running" | "done" | "failed"

    def to_dict(self) -> dict:
        from core.mission_planner import MissionPlan as _MP
        return {
            "macro_id":   self.macro_id,
            "description": self.description,
            "mission_type": self.mission_type,
            "complexity":  self.estimated_complexity,
            "status":      self.status,
            "tactical_steps": (
                [s.__dict__ for s in self.tactical_plan.steps]
                if isinstance(self.tactical_plan, _MP)
                else None
            ),
        }


@dataclass
class HierarchicalPlan:
    """Two-level plan: strategic macro-goals + tactical sub-plans."""
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    mission_id: str = ""
    original_goal: str = ""
    mission_type: str = ""
    macro_goals: list[MacroGoal] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def total_tactical_steps(self) -> int:
        from core.mission_planner import MissionPlan as _MP
        return sum(
            len(mg.tactical_plan.steps)
            for mg in self.macro_goals
            if isinstance(mg.tactical_plan, _MP)
        )

    def to_dict(self) -> dict:
        return {
            "plan_id":     self.plan_id,
            "mission_id":  self.mission_id,
            "goal":        self.original_goal[:200],
            "mission_type": self.mission_type,
            "macro_goals": [mg.to_dict() for mg in self.macro_goals],
            "total_tactical_steps": self.total_tactical_steps,
        }


# ── Decomposition patterns ─────────────────────────────────────────────────────
# (goal_keywords, [(macro_description_template, mission_type, complexity)])
_DECOMPOSITION_RULES: list[tuple[list[str], list[tuple[str, str, str]]]] = [
    (
        ["saas", "product", "startup", "application", "app", "platform"],
        [
            ("Analyser le marché et définir le périmètre du produit", "planning_task", "medium"),
            ("Concevoir l'architecture technique et les APIs", "architecture_task", "high"),
            ("Implémenter et tester les fonctionnalités core", "coding_task", "high"),
        ],
    ),
    (
        ["migrate", "refactor", "modernise", "modernize", "rearchitect"],
        [
            ("Analyser le système existant et identifier les contraintes", "research_task", "medium"),
            ("Planifier la stratégie de migration sans interruption de service", "planning_task", "high"),
            ("Exécuter la migration par phases avec validation", "coding_task", "high"),
        ],
    ),
    (
        ["security", "audit", "pentest", "vulnerabilit", "compliance", "sécurité"],
        [
            ("Cartographier la surface d'attaque et les actifs", "research_task", "medium"),
            ("Analyser les vulnérabilités et évaluer les risques", "evaluation_task", "high"),
            ("Produire le rapport de remédiation priorisé", "planning_task", "medium"),
        ],
    ),
    (
        ["pipeline", "ci/cd", "devops", "automation", "deploy", "docker", "kubernetes"],
        [
            ("Analyser le workflow actuel et définir les objectifs CI/CD", "planning_task", "medium"),
            ("Concevoir et implémenter le pipeline d'automatisation", "coding_task", "high"),
            ("Valider et documenter le pipeline en production", "evaluation_task", "medium"),
        ],
    ),
    (
        ["business", "strategy", "plan", "analyse", "analyze", "market", "revenue"],
        [
            ("Collecter et synthétiser les données clés du domaine", "research_task", "medium"),
            ("Analyser les opportunités, risques et facteurs critiques", "evaluation_task", "high"),
            ("Formuler les recommandations stratégiques actionnables", "planning_task", "medium"),
        ],
    ),
    (
        ["multi", "system", "architecture", "intégration", "integration", "microservice"],
        [
            ("Définir les exigences et les interfaces système", "planning_task", "medium"),
            ("Concevoir l'architecture et les contrats d'interface", "architecture_task", "high"),
            ("Implémenter et valider l'intégration bout-en-bout", "coding_task", "high"),
        ],
    ),
]

# Generic fallback (always matches if nothing else does)
_GENERIC_DECOMPOSITION: list[tuple[str, str, str]] = [
    ("Analyser et comprendre le contexte et les exigences", "research_task", "medium"),
    ("Concevoir et planifier la solution optimale", "planning_task", "high"),
    ("Implémenter, tester et valider la solution", "coding_task", "high"),
]


def _detect_macro_template(goal: str) -> list[tuple[str, str, str]]:
    """Match goal text against decomposition rules."""
    goal_lower = goal.lower()
    for keywords, macros in _DECOMPOSITION_RULES:
        if any(kw in goal_lower for kw in keywords):
            return macros
    return _GENERIC_DECOMPOSITION


# ── Main class ─────────────────────────────────────────────────────────────────

class MissionDecomposer:
    """
    Strategic decomposition of complex missions into macro-goals,
    each with a tactical MissionPlan.

    Usage:
        decomposer = MissionDecomposer()
        plan = decomposer.decompose(goal, mission_type, complexity, mission_id)
        if plan:
            # Two-level plan available
            for mg in plan.macro_goals:
                print(mg.description, mg.tactical_plan)
        else:
            # Fall back to flat MissionPlanner
    """

    def should_decompose(self, goal: str, complexity: str) -> bool:
        """Returns True only for high-complexity goals long enough to warrant hierarchy."""
        if complexity != "high":
            return False
        if len(goal.strip()) < HIERARCHICAL_MIN_GOAL_LEN:
            return False
        return True

    def decompose(
        self,
        goal: str,
        mission_type: str,
        complexity: str,
        mission_id: str = "",
    ) -> Optional[HierarchicalPlan]:
        """
        Build a HierarchicalPlan for the given goal.

        Returns None if:
        - `should_decompose()` returns False
        - decomposition produces fewer than MIN_MACRO_GOALS macro-goals
        - any exception occurs (fail-open)
        """
        if not self.should_decompose(goal, complexity):
            return None

        try:
            macro_templates = _detect_macro_template(goal)
            if len(macro_templates) < MIN_MACRO_GOALS:
                return None

            macro_templates = macro_templates[:MAX_MACRO_GOALS]

            # Build the tactical plan for each macro-goal
            from core.mission_planner import MissionPlanner
            planner = MissionPlanner()

            macro_goals: list[MacroGoal] = []
            for i, (desc, mt, cx) in enumerate(macro_templates):
                # Build sub-goal text for tactical planner
                sub_goal = f"{goal[:60]}… [{desc}]"
                tactical_plan = planner.build_plan(
                    goal=sub_goal,
                    mission_type=mt,
                    complexity=cx,
                    mission_id=f"{mission_id}_m{i}",
                )
                macro_goals.append(MacroGoal(
                    macro_id=i,
                    description=desc,
                    mission_type=mt,
                    estimated_complexity=cx,
                    tactical_plan=tactical_plan,
                ))

            plan = HierarchicalPlan(
                mission_id=mission_id,
                original_goal=goal,
                mission_type=mission_type,
                macro_goals=macro_goals,
            )

            log.info(
                "hierarchical_plan_built",
                plan_id=plan.plan_id,
                mission_id=mission_id,
                macro_goals=len(macro_goals),
                total_tactical_steps=plan.total_tactical_steps,
                goal_snippet=goal[:80],
            )
            return plan

        except Exception as exc:
            log.warning(
                "hierarchical_plan_failed",
                mission_id=mission_id,
                err=str(exc)[:120],
            )
            return None


# ── Singleton ──────────────────────────────────────────────────────────────────

_decomposer: MissionDecomposer | None = None


def get_mission_decomposer() -> MissionDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = MissionDecomposer()
    return _decomposer
