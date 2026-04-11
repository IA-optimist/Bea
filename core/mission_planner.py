"""
MissionPlanner — décomposition légère des missions complexes en sous-étapes.
Activé si complexity_score > 0.55.
Max 8 étapes, plan en mémoire runtime, pas de persistence.
RAM : ~20 KB max (8 étapes × ~2.5 KB).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import logging
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger(__name__)

# Seuil de complexité pour déclencher la planification
PLAN_COMPLEXITY_THRESHOLD = 0.55
MAX_PLAN_STEPS = 8
MIN_PLAN_STEPS = 2


@dataclass
class PlanStep:
    step_id: int                  # 0-based index
    description: str              # description courte de l'étape (~50 chars)
    mission_type: str             # type de la sous-mission (taxonomy v2)
    required_tools: List[str]     # tools du ToolRegistry recommandés
    required_agents: List[str]    # agents recommandés pour cette étape
    estimated_complexity: str     # "low" | "medium" | "high"
    depends_on: List[int]         # step_id des étapes dont celle-ci dépend
    status: str = "pending"       # "pending" | "running" | "done" | "failed"
    result_summary: str = ""      # résumé du résultat (rempli à l'exécution)


@dataclass
class MissionPlan:
    plan_id: str                         # unique, basé sur timestamp
    original_goal: str
    mission_type: str
    complexity: str
    steps: List[PlanStep]
    created_at: int = field(default_factory=lambda: int(time.time()))
    success_count: int = 0
    total_steps: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return round(self.success_count / self.total_steps, 3)


# ── Templates de décomposition par type de mission ────────────────────────
# Chaque template est une liste de (description_template, mission_type, tools, agents, complexity, depends_on)
_PLAN_TEMPLATES: Dict[str, List[tuple]] = {
    "create_project": [
        ("Analyser les exigences et définir la structure du projet", "planning_task", ["read_file"], ["map-planner"], "low", []),
        ("Créer l'architecture et les composants principaux", "architecture_task", ["write_file", "search_codebase"], ["map-planner", "lens-reviewer"], "medium", [0]),
        ("Implémenter le code de base", "coding_task", ["write_file", "run_command_safe"], ["forge-builder"], "medium", [1]),
        ("Tester et valider l'implémentation", "evaluation_task", ["run_command_safe", "check_logs"], ["lens-reviewer"], "low", [2]),
    ],
    "debug_system": [
        ("Reproduire et identifier le symptôme principal", "debug_task", ["check_logs", "read_file"], ["forge-builder"], "low", []),
        ("Analyser les logs et traces d'erreur", "debug_task", ["check_logs", "run_command_safe"], ["forge-builder"], "medium", [0]),
        ("Identifier la cause racine", "evaluation_task", ["search_codebase", "read_file"], ["lens-reviewer", "forge-builder"], "medium", [1]),
        ("Appliquer le correctif", "coding_task", ["write_file", "run_command_safe"], ["forge-builder"], "medium", [2]),
        ("Vérifier la correction", "evaluation_task", ["run_command_safe", "check_logs"], ["lens-reviewer"], "low", [3]),
    ],
    "analyze_code": [
        ("Cartographier la structure et les dépendances", "research_task", ["search_codebase", "read_file"], ["scout-research"], "low", []),
        ("Identifier les patterns et anti-patterns", "evaluation_task", ["search_codebase"], ["lens-reviewer"], "medium", [0]),
        ("Évaluer la qualité et les risques", "evaluation_task", ["read_file"], ["lens-reviewer", "shadow-advisor"], "medium", [1]),
        ("Produire le rapport d'analyse", "planning_task", [], ["map-planner"], "low", [2]),
    ],
    "deploy_service": [
        ("Vérifier l'environnement et les prérequis", "system_task", ["test_endpoint", "check_logs"], ["pulse-ops"], "low", []),
        ("Préparer la configuration de déploiement", "system_task", ["write_file", "read_file"], ["pulse-ops"], "medium", [0]),
        ("Exécuter le déploiement", "system_task", ["run_command_safe"], ["pulse-ops"], "high", [1]),
        ("Valider le service déployé", "evaluation_task", ["test_endpoint", "check_logs"], ["pulse-ops", "lens-reviewer"], "medium", [2]),
    ],
    "create_api": [
        ("Définir les endpoints et le contrat API", "architecture_task", ["read_file"], ["map-planner"], "low", []),
        ("Implémenter les routes et handlers", "coding_task", ["write_file"], ["forge-builder"], "medium", [0]),
        ("Ajouter validation et gestion d'erreurs", "coding_task", ["write_file", "search_codebase"], ["forge-builder"], "medium", [1]),
        ("Tester les endpoints", "evaluation_task", ["test_endpoint", "run_command_safe"], ["lens-reviewer"], "low", [2]),
        ("Documenter l'API", "planning_task", ["write_file"], ["map-planner"], "low", [3]),
    ],
    "improve_code": [
        ("Analyser le code existant et identifier les problèmes", "evaluation_task", ["search_codebase", "read_file"], ["lens-reviewer"], "low", []),
        ("Prioriser les améliorations", "planning_task", [], ["map-planner"], "low", [0]),
        ("Refactoriser le code ciblé", "coding_task", ["write_file", "search_codebase"], ["forge-builder"], "medium", [1]),
        ("Vérifier les régressions", "evaluation_task", ["run_command_safe"], ["lens-reviewer"], "low", [2]),
    ],
    "write_docs": [
        ("Analyser le code et fonctionnalités à documenter", "research_task", ["search_codebase", "read_file"], ["scout-research"], "low", []),
        ("Rédiger la documentation principale", "planning_task", ["write_file"], ["map-planner"], "medium", [0]),
        ("Ajouter exemples et cas d'usage", "planning_task", ["write_file"], ["map-planner"], "low", [1]),
        ("Réviser et valider la doc", "evaluation_task", ["read_file"], ["lens-reviewer"], "low", [2]),
    ],
    "test_system": [
        ("Identifier les composants critiques à tester", "evaluation_task", ["search_codebase"], ["lens-reviewer"], "low", []),
        ("Écrire les cas de test", "coding_task", ["write_file"], ["forge-builder"], "medium", [0]),
        ("Exécuter les tests", "evaluation_task", ["run_command_safe", "check_logs"], ["lens-reviewer"], "medium", [1]),
        ("Analyser les résultats et corriger", "debug_task", ["check_logs", "write_file"], ["forge-builder", "lens-reviewer"], "medium", [2]),
    ],
}

# Mapping mission_type → template de décomposition
_MISSION_TO_TEMPLATE = {
    "coding_task":      "create_project",
    "debug_task":       "debug_system",
    "architecture_task":"analyze_code",
    "system_task":      "deploy_service",
    "evaluation_task":  "analyze_code",
    "research_task":    "analyze_code",
    "planning_task":    "create_project",
    "business_task":    "write_docs",
    "self_improvement_task": "analyze_code",
    "info_query":       None,   # pas de plan pour les requêtes simples
    "compare_query":    None,
}

# Mots-clés pour détecter le type de décomposition dans le goal
_GOAL_TO_TEMPLATE = {
    "api":          "create_api",
    "endpoint":     "create_api",
    "route":        "create_api",
    "deploy":       "deploy_service",
    "docker":       "deploy_service",
    "serveur":      "deploy_service",
    "server":       "deploy_service",
    "debug":        "debug_system",
    "bug":          "debug_system",
    "erreur":       "debug_system",
    "error":        "debug_system",
    "test":         "test_system",
    "tester":       "test_system",
    "doc":          "write_docs",
    "documentation":"write_docs",
    "améliore":     "improve_code",
    "refactor":     "improve_code",
    "optimize":     "improve_code",
    "analyse":      "analyze_code",
    "analyze":      "analyze_code",
    "crée":         "create_project",
    "create":       "create_project",
    "build":        "create_project",
    "projet":       "create_project",
}


def _detect_template(goal: str, mission_type: str) -> Optional[str]:
    """Détecte le template de décomposition le plus adapté."""
    goal_lower = goal.lower()
    # Priorité aux mots-clés du goal
    for keyword, template in _GOAL_TO_TEMPLATE.items():
        if keyword in goal_lower:
            return template
    # Fallback sur mission_type
    return _MISSION_TO_TEMPLATE.get(mission_type)


class MissionPlanner:
    """
    Décompose les missions complexes (score > 0.55) en sous-étapes exécutables.
    Chaque étape est compatible avec le routing normal (taxonomy v2 + capability_registry).
    """

    def should_plan(self, complexity: str, confidence_score: float, mission_type: str) -> bool:
        """
        Détermine si la mission nécessite une planification multi-étapes.
        """
        # Pas de plan pour les requêtes simples
        if mission_type in ("info_query", "compare_query", "self_improvement_task"):
            return False
        if complexity == "low":
            return False
        # Score de complexité estimé
        complexity_score = {"low": 0.2, "medium": 0.5, "high": 0.8}.get(complexity, 0.5)
        # Facteur confiance inverse (faible confiance = besoin de planifier)
        planning_score = complexity_score * (1.0 - confidence_score * 0.3)
        return planning_score > PLAN_COMPLEXITY_THRESHOLD

    def build_plan(
        self,
        goal: str,
        mission_type: str,
        complexity: str,
        mission_id: str,
    ) -> Optional[MissionPlan]:
        """
        Construit un plan d'exécution multi-étapes.
        Retourne None si la planification échoue (fail-open).
        """
        try:
            template_name = _detect_template(goal, mission_type)
            if template_name is None:
                return None

            template = _PLAN_TEMPLATES.get(template_name, [])
            if not template:
                return None

            # Adapte le nombre d'étapes à la complexité
            if complexity == "medium":
                max_steps = min(4, MAX_PLAN_STEPS)
            else:
                max_steps = MAX_PLAN_STEPS

            steps_data = template[:max_steps]
            if len(steps_data) < MIN_PLAN_STEPS:
                return None

            # ── Adaptive enrichment from mission memory (fail-open) ─────
            proven_tools = []
            proven_agents = []
            _adapted = False
            try:
                from core.mission_memory import get_mission_memory
                _mm = get_mission_memory()
                _best = _mm.get_best_strategy(mission_type)
                if _best and _best.get("confidence", 0) >= 0.5:
                    proven_tools = _best.get("tools", [])[:8]
                    proven_agents = _best.get("agents", [])[:4]
                    _adapted = True
            except Exception:
                _silent_log.debug("suppressed_exception", src='mission_planner.py')

            # ── Exclude known-failing tools (fail-open) ───────────────
            _degraded_tools = set()
            try:
                from core.tool_performance_tracker import get_tool_performance_tracker
                _tpt = get_tool_performance_tracker()
                for ft in _tpt.get_failing_tools():
                    _degraded_tools.add(ft["tool"])
            except Exception:
                _silent_log.debug("suppressed_exception", src='mission_planner.py')

            steps = []
            for i, (desc, mt, tools, agents, cx, deps) in enumerate(steps_data):
                # Personnalise la description avec des mots du goal (premier mot significatif)
                goal_words = [w for w in goal.lower().split() if len(w) > 3][:2]
                goal_hint = " ".join(goal_words) if goal_words else ""
                full_desc = f"{desc}" + (f" [{goal_hint}]" if goal_hint else "")

                # Adaptive: replace template tools/agents with proven ones if available
                step_tools = list(tools)
                step_agents = list(agents)
                if _adapted and proven_tools:
                    # Merge: proven tools first, then template tools, skip degraded
                    merged_tools = []
                    for t in proven_tools + step_tools:
                        if t not in merged_tools and t not in _degraded_tools:
                            merged_tools.append(t)
                    step_tools = merged_tools[:6]
                if _adapted and proven_agents:
                    step_agents = proven_agents[:3]

                # Remove degraded tools even without adaptation
                step_tools = [t for t in step_tools if t not in _degraded_tools]

                steps.append(PlanStep(
                    step_id=i,
                    description=full_desc[:120],  # tronque à 120 chars
                    mission_type=mt,
                    required_tools=step_tools,
                    required_agents=step_agents,
                    estimated_complexity=cx,
                    depends_on=list(deps),
                ))

            plan = MissionPlan(
                plan_id=f"plan_{mission_id}_{int(time.time())}",
                original_goal=goal[:200],
                mission_type=mission_type,
                complexity=complexity,
                steps=steps,
                total_steps=len(steps),
            )

            _adapted_msg = " (adapted from memory)" if _adapted else ""
            logger.info(f"[MissionPlanner] built plan '{template_name}' with {len(steps)} steps{_adapted_msg} for mission {mission_id}")
            return plan

        except Exception as e:
            logger.warning(f"[MissionPlanner] build_plan error: {e}")
            return None

    def execute_step(self, step: PlanStep) -> bool:
        """
        Marque une étape comme en cours. Retourne True.
        L'exécution réelle est gérée par _run_mission() via le routing normal.
        """
        step.status = "running"
        return True

    def complete_step(self, step: PlanStep, result_summary: str, success: bool) -> None:
        """Marque une étape comme terminée."""
        step.status = "done" if success else "failed"
        step.result_summary = result_summary[:300]

    def get_next_steps(self, plan: MissionPlan) -> List[PlanStep]:
        """
        Retourne les étapes exécutables (dépendances satisfaites, status pending).
        Exécution séquentielle : retourne au max 1 étape à la fois.
        """
        done_ids = {s.step_id for s in plan.steps if s.status == "done"}
        for step in plan.steps:
            if step.status == "pending":
                if all(dep in done_ids for dep in step.depends_on):
                    return [step]
        return []

    def plan_to_dict(self, plan: MissionPlan) -> dict:
        """Sérialise le plan pour l'API."""
        return {
            "plan_id": plan.plan_id,
            "original_goal": plan.original_goal,
            "mission_type": plan.mission_type,
            "complexity": plan.complexity,
            "total_steps": plan.total_steps,
            "success_rate": plan.success_rate,
            "created_at": plan.created_at,
            "steps": [
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "mission_type": s.mission_type,
                    "required_tools": s.required_tools,
                    "required_agents": s.required_agents,
                    "estimated_complexity": s.estimated_complexity,
                    "depends_on": s.depends_on,
                    "status": s.status,
                    "result_summary": s.result_summary,
                }
                for s in plan.steps
            ],
        }


    def slice_mission(self, goal: str, mission_type: str,
                      complexity: str) -> list[dict]:
        """
        Slice a complex goal into sub-missions.
        Returns a list of sub-mission specs that can be submitted independently.
        Only slices if complexity is high or goal is multi-part.
        """
        # Only slice complex missions
        if complexity not in ("high",):
            return [{"goal": goal, "mission_type": mission_type, "complexity": complexity}]

        # Detect multi-part goals
        goal_lower = goal.lower()
        parts = []

        # Split on conjunctions/semicolons
        for sep in [" and then ", " puis ", " then ", " et ", "; ", " + "]:
            if sep in goal_lower:
                raw_parts = goal.split(sep if sep != sep.lower() else sep)
                parts = [p.strip() for p in raw_parts if len(p.strip()) > 10]
                break

        if len(parts) < 2:
            # Try keyword-based decomposition
            if any(kw in goal_lower for kw in ("build", "create", "develop")):
                parts = [
                    f"Research and plan: {goal}",
                    f"Implement core: {goal}",
                    f"Test and validate: {goal}",
                ]
            elif any(kw in goal_lower for kw in ("analyze", "audit", "review")):
                parts = [
                    f"Collect data for: {goal}",
                    f"Analyze findings: {goal}",
                    f"Generate report: {goal}",
                ]
            else:
                # Single mission, no slicing
                return [{"goal": goal, "mission_type": mission_type, "complexity": complexity}]

        # Build sub-missions with appropriate types
        sub_missions = []
        type_sequence = {
            0: "research_task",
            1: mission_type,  # main type for core work
            2: "evaluation_task",
        }
        for i, part in enumerate(parts[:5]):  # Max 5 sub-missions
            sub_type = type_sequence.get(i, mission_type)
            sub_missions.append({
                "goal": part[:200],
                "mission_type": sub_type,
                "complexity": "medium",  # Sub-missions are simpler
                "parent_goal": goal[:200],
                "sequence": i,
                "total": len(parts),
            })

        return sub_missions


# Singleton
_planner: Optional[MissionPlanner] = None
_last_plan: Optional[MissionPlan] = None  # Dernier plan en mémoire (pour l'endpoint)

def get_mission_planner() -> MissionPlanner:
    global _planner
    if _planner is None:
        _planner = MissionPlanner()
    return _planner

def get_last_plan() -> Optional[MissionPlan]:
    return _last_plan

def set_last_plan(plan: MissionPlan) -> None:
    global _last_plan
    _last_plan = plan
