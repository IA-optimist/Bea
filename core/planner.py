"""
Planner — interface robuste de planification avec fallback automatique.
Délègue à MissionPlanner avec try/except complet.
En cas d'exception : retourne un plan minimal {"steps": ["fallback: direct execution"], "error": ...}
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("jarvis.planner")

try:
    from core.tool_registry import rank_tools_for_task, should_create_tool
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.knowledge.pattern_detector import detect_patterns as _detect_patterns
    _KNOWLEDGE_AVAILABLE = True
except ImportError:
    _KNOWLEDGE_AVAILABLE = False

try:
    from core.knowledge.difficulty_estimator import estimate_difficulty as _estimate_difficulty
    _DIFFICULTY_AVAILABLE = True
except ImportError:
    _DIFFICULTY_AVAILABLE = False

# ── Objective Engine — import fail-open ───────────────────────────────────────
try:
    from core.objectives.objective_engine import get_objective_engine as _get_objective_engine
    _OBJECTIVE_ENGINE_AVAILABLE = True
except ImportError:
    _OBJECTIVE_ENGINE_AVAILABLE = False

# ── Self-Improvement — import fail-open ───────────────────────────────────────
try:
    from core.self_improvement import check_improvement_allowed as _check_improvement_allowed
    _SI_AVAILABLE = True
except ImportError:
    _SI_AVAILABLE = False


def _get_objective_context(goal: str, mission_type: str) -> Optional[dict]:
    """
    Injecte le contexte d'objectif actif lié au goal dans le plan.
    Fail-open : retourne None si engine indisponible ou en erreur.
    """
    if not _OBJECTIVE_ENGINE_AVAILABLE:
        return None
    try:
        engine = _get_objective_engine()
        similar = engine.find_similar(goal)
        if not similar:
            return None
        # Prendre le plus pertinent
        top = similar[0]
        objective_id = top.get("objective_id")
        if not objective_id:
            return None
        obj = engine.get(objective_id)
        if obj is None:
            return None
        nba = engine.get_next_best_action(goal_hint=goal)
        return {
            "active_objective_id":     obj.objective_id,
            "active_objective_title":  obj.title,
            "active_objective_status": obj.status,
            "active_priority_score":   obj.priority_score,
            "next_best_action":        nba.get("action_type"),
            "next_best_node":          nba.get("node_title"),
            "required_tools":          nba.get("required_tools", []),
        }
    except Exception:
        return None  # fail-open absolu


def _search_similar_patterns(goal: str, mission_type: str) -> Optional[dict]:
    """
    Cherche des patterns similaires dans la mémoire de Jarvis avant de planifier.
    Retourne un dict de contexte ou None si rien de trouvé.
    Fail-open : jamais d'exception levée.
    """
    if not _KNOWLEDGE_AVAILABLE:
        return None
    try:
        patterns = _detect_patterns(goal=goal, mission_type=mission_type)
        if not patterns.get("has_prior_knowledge"):
            return None
        return patterns
    except Exception:
        return None


def _build_reasoning_summary(task: str, plan: dict, chosen_tools: list) -> dict:
    """
    Génère un résumé de raisonnement pour chaque plan.
    Format court, lisible.
    """
    steps = plan.get("steps", [])
    complexity_warning = None
    if len(steps) > 4 and len(chosen_tools) <= 1:
        complexity_warning = "WARNING: plan may be over-engineered for single-tool task"

    return {
        "reasoning_summary": f"Task requires {len(chosen_tools)} tool(s) in {len(steps)} step(s)",
        "chosen_tools": chosen_tools,
        "estimated_steps": len(steps),
        "risk_level": plan.get("risk_level", "low"),
        "complexity_warning": complexity_warning,
        "simplicity_score": max(0.0, 1.0 - (len(steps) - 1) * 0.1),
    }


def _simplify_plan_if_possible(plan: dict, task: str) -> dict:
    """
    Si la solution est possible avec 1 tool très pertinent (score > 0.8),
    réduire le plan à 1 étape. Règle : ne pas créer workflow 6 étapes si 1 tool suffit.
    """
    steps = plan.get("steps", [])
    if len(steps) <= 2:
        return plan  # déjà simple

    if _REGISTRY_AVAILABLE:
        try:
            ranked = rank_tools_for_task(task, top_k=1)
            if ranked and ranked[0]["score"] > 0.8:
                plan["steps"] = steps[:1]
                plan["simplified"] = True
                plan["simplification_reason"] = (
                    f"Single tool '{ranked[0]['name']}' highly relevant (score: {ranked[0]['score']})"
                )
        except Exception:
            logger.debug("swallowed_exception", exc_info=True)
    return plan


# Limites de sécurité anti-boucle
MAX_PLAN_ITERATIONS = 5
MAX_STEPS_PER_PLAN = 8

# Routing recommandé par type de mission
MISSION_TOOL_ROUTING: dict[str, list[str]] = {
    "bug_fix":      ["file_search", "replace_in_file", "run_unit_tests"],
    "deploy":       ["git_commit", "git_push", "docker_compose_build", "docker_compose_up", "api_healthcheck"],
    "analysis":     ["memory_search_similar", "search_in_files", "http_get"],
    "research":     ["fetch_url", "doc_fetch", "search_pypi", "memory_store_solution"],
    "test":         ["run_unit_tests", "run_smoke_tests", "api_healthcheck"],
    "improvement":  ["search_in_files", "replace_in_file", "run_unit_tests", "memory_store_patch"],
    "cybersecurity":["file_search", "dependency_analyzer", "env_checker"],
    "saas_creation":["file_create", "api_schema_generator", "generate_tool_skeleton"],
    "ceo_planning": ["memory_search_similar", "build_plan", "memory_store_solution"],
}


def build_plan(
    goal: str,
    mission_type: str = "coding_task",
    complexity: str = "medium",
    mission_id: str = "unknown",
) -> dict:
    """
    Construit un plan d'exécution via MissionPlanner.
    Retourne toujours un dict avec clé "steps" — jamais d'exception levée.
    """
    try:
        # Estimation de difficulté avant planification (fail-open)
        difficulty_info: dict = {}
        if _DIFFICULTY_AVAILABLE:
            try:
                difficulty_info = _estimate_difficulty(goal=goal, mission_type=mission_type)
            except Exception as e:
                logger.debug("difficulty_estimation_skipped: %s", str(e)[:80])

        # Recherche de patterns similaires avant planification (fail-open)
        prior_knowledge = _search_similar_patterns(goal, mission_type)

        # ── Knowledge graph: similar missions + successful strategies ─────
        _kg_context = {}
        try:
            from core.knowledge_memory import get_knowledge_memory
            _km = get_knowledge_memory()
            _km_result = _km.find_similar(goal, mission_type)
            if _km_result is not None:
                _km_entry, _km_score = _km_result
                if _km_score >= 0.3:
                    _kg_context = {
                        "similar_mission_score": round(_km_score, 3),
                        "prior_tools": _km_entry.tools_used,
                        "prior_agents": _km_entry.agents_used,
                        "prior_success": _km_entry.success,
                    }
        except Exception as _kg_err:
            logger.debug("kg_planner_context_skipped: %s", str(_kg_err)[:60])

        # ── Memory Facade: unified search for prior mission outcomes (P5) ─
        _facade_context: list[dict] = []
        try:
            from core.memory_facade import get_memory_facade
            _mf = get_memory_facade()
            _mf_results = _mf.search(goal[:200], top_k=3)
            _facade_context = [
                {"content": e.content[:300], "score": e.score, "source": e.source}
                for e in _mf_results if e.score >= 0.3
            ]
        except Exception as _mf_err:
            logger.debug("memory_facade_search_skipped: %s", str(_mf_err)[:60])

        # ── Agent routing intelligence for planner ────────────────────────
        _routing_context = {}
        try:
            from core.dynamic_agent_router import get_routing_explanation
            _routing_context = get_routing_explanation(
                mission_type=mission_type,
                complexity=complexity,
                static_agents=MISSION_TOOL_ROUTING.get(mission_type, []),
            )
        except Exception as _rt_err:
            logger.debug("routing_context_skipped: %s", str(_rt_err)[:60])
        # ── end knowledge + routing context ───────────────────────────────

        # Contexte objectif actif (fail-open)
        objective_context = _get_objective_context(goal, mission_type)

        from core.mission_planner import get_mission_planner
        planner = get_mission_planner()
        plan = planner.build_plan(
            goal=goal,
            mission_type=mission_type,
            complexity=complexity,
            mission_id=mission_id,
        )
        if plan is not None:
            result = planner.plan_to_dict(plan)
        else:
            # Mission simple → exécution directe sans étapes
            result = {"steps": ["direct execution"], "error": None}
        # Enrichir avec le routing recommandé si le mission_type est connu
        recommended_tools = MISSION_TOOL_ROUTING.get(mission_type, [])
        if recommended_tools:
            result["recommended_tools"] = recommended_tools

        # ── Operating primitives: feasibility + strategy (fail-open) ────────
        _feasibility = None
        _strategy_rec = None
        try:
            from core.safety_controls import is_intelligence_enabled
            if is_intelligence_enabled():
                from core.operating_primitives import score_feasibility, select_strategy
                _feasibility = score_feasibility(goal, mission_type, recommended_tools, complexity)
                _strategy_rec = select_strategy(goal, mission_type, complexity)
                result["feasibility_score"] = _feasibility.overall
                result["feasibility_missing_tools"] = _feasibility.missing_tools
                if _strategy_rec.source != "default":
                    result["strategy_recommendation"] = _strategy_rec.to_dict()
        except Exception as _op_err:
            logger.debug("operating_primitives_skipped: %s", str(_op_err)[:60])
        # ── end operating primitives ──────────────────────────────────────

        # ── Real performance intelligence (fail-open, gated by safety flag) ──
        try:
            from core.safety_controls import is_intelligence_enabled
            if not is_intelligence_enabled():
                raise RuntimeError("intelligence_disabled")
            from core.mission_performance_tracker import get_mission_performance_tracker
            _mpt = get_mission_performance_tracker()
            _strategy = _mpt.get_strategy_for_type(mission_type)
            if _strategy and _strategy.get("sample_size", 0) >= 2:
                result["performance_intelligence"] = _strategy
                # Reorder recommended_tools by real success data
                _tool_scores = dict(_strategy.get("recommended_tools", []))
                if _tool_scores and recommended_tools:
                    recommended_tools.sort(
                        key=lambda t: _tool_scores.get(t, 0), reverse=True
                    )
                    result["recommended_tools"] = recommended_tools
                # Inject best agents from real data
                _best_agents = _mpt.get_best_agents_for_type(mission_type)
                if _best_agents:
                    result["performance_recommended_agents"] = _best_agents
        except Exception as _pi_err:
            logger.debug("perf_intelligence_skipped: %s", str(_pi_err)[:60])

        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            _tpt = get_tool_performance_tracker()
            _failing = _tpt.get_failing_tools()
            if _failing:
                result["degraded_tools"] = [t["tool"] for t in _failing[:5]]
            # Rank candidates by reliability
            if recommended_tools:
                _best = _tpt.get_tool_for_capability(recommended_tools)
                if _best:
                    result["primary_tool_recommendation"] = _best
        except Exception as _tpi_err:
            logger.debug("tool_perf_intelligence_skipped: %s", str(_tpi_err)[:60])
        # ── Mission memory: cross-mission strategy reuse ───────────────
        try:
            from core.mission_memory import get_mission_memory
            _mm = get_mission_memory()
            _best_strategy = _mm.get_best_strategy(mission_type)
            if _best_strategy and _best_strategy.get("confidence", 0) >= 0.5:
                result["proven_strategy"] = _best_strategy
            _effective_seqs = _mm.get_effective_sequences(mission_type, top_k=3)
            if _effective_seqs:
                result["effective_tool_sequences"] = _effective_seqs
            _failing = _mm.get_failing_patterns(min_failures=2)
            if _failing:
                result["known_failing_patterns"] = [
                    {"agents": f["agents"], "tools": f["tools"], "rate": f["success_rate"]}
                    for f in _failing if f["mission_type"] == mission_type
                ][:3]
        except Exception as _mm_err:
            logger.debug("mission_memory_skipped: %s", str(_mm_err)[:60])
        # ── end real performance intelligence ─────────────────────────────

        # Injecter les patterns similaires si trouvés
        if prior_knowledge:
            result["prior_knowledge"] = prior_knowledge
        # Injecter le contexte knowledge graph
        if _kg_context:
            result["knowledge_graph_context"] = _kg_context
            # If prior mission was successful, boost those tools
            if _kg_context.get("prior_success") and _kg_context.get("prior_tools"):
                _prior_tools = _kg_context["prior_tools"]
                _existing = result.get("recommended_tools", [])
                for pt in _prior_tools:
                    if pt not in _existing:
                        _existing.append(pt)
                result["recommended_tools"] = _existing
        # Inject facade memory context (P5 — unified search)
        if _facade_context:
            result["memory_facade_context"] = _facade_context
        # Injecter routing context
        if _routing_context:
            result["routing_intelligence"] = _routing_context
        # Injecter le contexte objectif actif (fail-open)
        if objective_context:
            result["objective_context"] = objective_context
        # Injecter le contexte self-improvement (fail-open)
        try:
            si_context = {"improvement_allowed": _check_improvement_allowed()} if _SI_AVAILABLE else {"improvement_allowed": False}
        except ImportError:
            si_context = {"improvement_allowed": False}
        result["self_improvement_context"] = si_context
        # Tool Intelligence hints — fail-open, active si USE_TOOL_INTELLIGENCE=true
        try:
            from core.tool_intelligence.planner_hints import get_hints_for_planner
            result["tool_intelligence_hints"] = get_hints_for_planner(
                available_tools=result.get("recommended_tools", []), objective=goal or ""
            )
        except Exception:
            result["tool_intelligence_hints"] = {}
        # Injecter la difficulté estimée
        if difficulty_info:
            result["difficulty_score"] = difficulty_info.get("score", 0.5)
            result["difficulty_label"] = difficulty_info.get("label", "MEDIUM")
            result["difficulty_reasons"] = difficulty_info.get("reasons", [])
        # Simplification et raisonnement
        result = _simplify_plan_if_possible(result, goal)
        chosen_tools = result.get("recommended_tools", [])
        result["reasoning"] = _build_reasoning_summary(goal, result, chosen_tools)
        # Analyse de création de tool si registry disponible
        if _REGISTRY_AVAILABLE:
            try:
                tool_decision = should_create_tool(goal)
                result["tool_creation_advice"] = tool_decision
            except Exception as e:
                logger.debug("tool_creation_advice_skipped: %s", str(e)[:80])
        return result
    except Exception as e:
        logger.warning(f"[PLANNER_FALLBACK] {e}")
        recommended_tools = MISSION_TOOL_ROUTING.get(mission_type, [])
        return {
            "steps": ["fallback: direct execution"],
            "error": str(e),
            "recommended_tools": recommended_tools,
        }


# ── Helpers anti-loop et validation (V3) ──────────────────────────────────────

def _validate_plan_feasibility(plan: dict, available_tools: list) -> tuple:
    """
    Vérifie que chaque step du plan référence un tool disponible.

    Returns:
        (is_feasible: bool, reason: str)
    """
    try:
        steps = plan.get("steps", [])
        if not steps:
            return False, "plan has no steps"
        for step in steps:
            step_str = str(step).lower()
            # Si un step mentionne un tool explicitement inconnu
            for word in step_str.split():
                clean = word.strip(".,:()")
                if clean and "_" in clean and clean not in available_tools:
                    # Seulement alerter sur les noms qui ressemblent à des tools (snake_case)
                    if len(clean) > 4 and all(c.isalnum() or c == "_" for c in clean):
                        logger.debug(f"[PLANNER] unknown tool ref: {clean}")
        return True, "ok"
    except Exception as e:
        return True, f"validation_error: {e}"


def _detect_infinite_loop_risk(steps: list) -> bool:
    """
    Vérifie si steps contient 2 fois la même action consécutive
    ou si un tool est référencé 3+ fois.

    Returns:
        True si risque de boucle détecté
    """
    try:
        if not steps:
            return False
        # Vérifier actions consécutives identiques
        for i in range(len(steps) - 1):
            if str(steps[i]).strip() == str(steps[i + 1]).strip():
                logger.warning(f"[PLANNER] consecutive duplicate step: {steps[i]}")
                return True
        # Vérifier tool utilisé 3+ fois
        from collections import Counter
        counts = Counter(str(s).strip() for s in steps)
        for step, count in counts.items():
            if count >= 3:
                logger.warning(f"[PLANNER] step repeated {count}x: {step}")
                return True
        return False
    except Exception:
        return False


def _compute_tool_confidence(tool_name: str) -> float:
    """
    Retourne un score de confiance 0.0-1.0 basé sur l'historique (memory_toolkit).
    Fallback: 0.5 si aucun historique.

    Returns:
        float entre 0.0 et 1.0
    """
    try:
        from core.tools.memory_toolkit import memory_search_similar
        result = memory_search_similar(query=f"tool_error:{tool_name}", top_k=5)
        if result.get("status") != "ok":
            return 0.5
        output = result.get("output", "")
        found_count = int(output.split("found=")[1].split("\n")[0]) if "found=" in output else 0
        # Plus d'erreurs trouvées → confiance réduite
        if found_count == 0:
            return 0.8
        elif found_count <= 2:
            return 0.6
        else:
            return 0.3
    except Exception:
        return 0.5


def _add_fallback_step(plan: dict, error_context: str) -> dict:
    """
    Ajoute un step 'fallback: direct_execution' si plan vide ou non faisable.

    Returns:
        Plan enrichi avec step fallback
    """
    try:
        steps = plan.get("steps", [])
        if not steps or steps == ["fallback: direct execution"]:
            plan["steps"] = [f"fallback: direct_execution (context: {error_context[:80]})"]
            plan["has_fallback"] = True
        else:
            plan["steps"].append(f"fallback: direct_execution (context: {error_context[:80]})")
            plan["has_fallback"] = True
        return plan
    except Exception:
        return {"steps": ["fallback: direct_execution"], "has_fallback": True, "error": error_context}


class Planner:
    """Interface objet — wrapper de build_plan() avec fallback garanti."""

    def plan(
        self,
        goal: str,
        mission_type: str = "coding_task",
        complexity: str = "medium",
        mission_id: str = "unknown",
    ) -> dict:
        return build_plan(
            goal=goal,
            mission_type=mission_type,
            complexity=complexity,
            mission_id=mission_id,
        )


# ── Singleton ──────────────────────────────────────────────────────────────────

_planner: Optional[Planner] = None


def get_planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner
