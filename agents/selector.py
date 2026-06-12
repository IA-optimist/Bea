"""Agent selection routing extracted from agents.crew.

The public compatibility imports remain in agents.crew while this module owns
mission-to-agent selection rules.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)
_silent_log = structlog.get_logger(__name__)
# ── AgentSelector (V1 optimisé) ──────────────────────────────────────────────

# Profils agents par rôle
AGENT_PROFILES = {
    "scout-research": {"domains": ["research", "analysis", "business", "cyber"], "cost": 1},
    "map-planner":    {"domains": ["all"], "cost": 1},
    "shadow-advisor": {"domains": ["all"], "cost": 1},
    "forge-builder":  {"domains": ["dev", "saas", "automation", "file"], "cost": 2},
    "lens-reviewer":  {"domains": ["all"], "cost": 1},
    "vault-memory":   {"domains": ["memory", "history", "context"], "cost": 1},
    "pulse-ops":      {"domains": ["ops", "monitoring", "infra"], "cost": 2},
}

MAX_AGENTS_PER_MISSION = 5

# Mission-type-first routing table (taxonomy v2)
MISSION_ROUTING: dict[str, list[str]] = {
    "coding_task":           ["forge-builder"],
    "debug_task":            ["forge-builder", "lens-reviewer"],
    "architecture_task":     ["map-planner", "lens-reviewer"],
    "system_task":           ["pulse-ops"],
    "planning_task":         ["map-planner"],
    "business_task":         ["scout-research", "map-planner"],
    "research_task":         ["scout-research"],
    "info_query":            ["scout-research"],
    "compare_query":         ["scout-research", "lens-reviewer"],
    "evaluation_task":       ["lens-reviewer"],
    "self_improvement_task": ["shadow-advisor"],
}

# Agents préférés par domaine (Phase 5 — DomainRouter)
DOMAIN_AGENT_PROFILES: dict[str, list[str]] = {
    "software_dev":  ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "ai_engineer":   ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "cyber_security":["scout-research", "shadow-advisor", "map-planner", "lens-reviewer"],
    "automation":    ["map-planner", "forge-builder", "lens-reviewer"],
    "business":      ["scout-research", "map-planner", "shadow-advisor", "lens-reviewer"],
    "saas_builder":  ["scout-research", "map-planner", "forge-builder", "shadow-advisor", "lens-reviewer"],
    "general":       ["map-planner", "lens-reviewer"],
}


class AgentSelector:
    """
    Sélectionne le minimum d'agents nécessaires pour une mission.

    Règles V1 :
    - Toujours : map-planner, lens-reviewer
    - scout-research si mots-clés research/analysis/report/context
    - shadow-advisor si MEDIUM/HIGH risk ou mots-clés risk/security/delete/modify
    - forge-builder UNIQUEMENT si mots-clés code/file/create/build/write/script
    - vault-memory UNIQUEMENT si mots-clés memory/history/past/remember
    - pulse-ops UNIQUEMENT si mots-clés monitor/infra/ops/deploy/status
    - Jamais > MAX_AGENTS_PER_MISSION (5)
    """

    _ALWAYS = ["map-planner", "lens-reviewer"]

    _RESEARCH_KW = frozenset({
        "research", "recherche", "analyse", "analyser", "analysis", "report",
        "rapport", "bilan", "context", "contexte", "inspect", "audit",
        "étude", "synthèse", "investigate", "explore",
    })
    _RISK_KW = frozenset({
        "risk", "risque", "security", "sécurité", "delete", "supprimer", "drop",
        "modify", "modifier", "remove", "dangerous", "critical", "exploit",
        "vulnerability", "pentest",
    })
    _CODE_KW = frozenset({
        "code", "créer", "crée", "create", "file", "fichier", "build", "write",
        "écrire", "script", "programme", "function", "fonction", "class", "module",
        "api", "library", "test", "debug", "bug", "implement", "développe",
    })
    _MEMORY_KW = frozenset({
        "memory", "mémoire", "history", "historique", "past", "passé",
        "remember", "souviens", "rappelle", "précédent",
    })
    _OPS_KW = frozenset({
        "monitor", "monitoring", "infra", "infrastructure", "ops", "deploy",
        "deployment", "status", "cron", "pipeline", "service", "container",
    })

    _PLANNING_KW = frozenset({
        "plan", "roadmap", "étapes", "phases", "strategy", "architecture",
    })

    @staticmethod
    def _ensure_file_builder(agents: list[str], g: str) -> list[str]:
        """Garantit forge-builder quand le goal exige un livrable fichier.

        Une mission au format '### Fichier:' sans forge-builder ne peut produire
        AUCUN fichier (seul agent dont la sortie est parsée en actions create_file).
        Le cap MAX_AGENTS et le path 'medium' le faisaient sauter silencieusement.
        """
        if "### fichier" in g and "forge-builder" not in agents:
            agents = ["forge-builder"] + agents
            if len(agents) > MAX_AGENTS_PER_MISSION:
                # forge-builder vient d'être inséré en tête — couper la queue
                agents = agents[:MAX_AGENTS_PER_MISSION]
            log.info("forge_builder_forced", reason="file_deliverable_in_goal",
                     agents=agents)
        return agents

    def select_agents(
        self,
        goal: str,
        risk_level: str = "LOW",
        domain: str = "general",
        mission_type: str = "",
        preferred_agents: list[str] | None = None,
        complexity: str = "medium",
    ) -> list[str]:
        """
        Retourne la liste minimale des agents à activer.
        Ne dépasse jamais MAX_AGENTS_PER_MISSION.
        Piloté par complexity : low=1 agent, medium=2-3, high=logique complète.
        """
        from core.mission_system import is_capability_query
        if is_capability_query(goal):
            log.info("agent_selector_capability_query", goal=goal[:60])
            return []

        g  = goal.lower()
        rl = risk_level.upper()
        cx = complexity.lower()

        # ── PolicyMode override (fail-open) ─────────────────────────────────
        try:
            from core.policy_mode import get_policy_mode_store
            _pm = get_policy_mode_store().get().value
        except Exception:
            _pm = "BALANCED"
        # Sera utilisé plus bas pour SAFE cap et UNCENSORED boost
        # ── end PolicyMode read ──────────────────────────────────────────────

        # ── MISSION_TYPE-FIRST ROUTING ────────────────────────────────────────
        if mission_type in MISSION_ROUTING:
            base = list(MISSION_ROUTING[mission_type])
            if cx == "low":
                agents = base[:1]
            elif cx == "medium":
                agents = base[:2]
            else:  # high
                agents = list(base)
                if rl in ("MEDIUM", "HIGH") and "shadow-advisor" not in agents:
                    agents.append("shadow-advisor")

            # ── Dynamic routing overlay (fail-open) ──────────────────────
            try:
                from core.dynamic_agent_router import route_agents
                agents = route_agents(
                    goal=goal,
                    mission_type=mission_type,
                    complexity=cx,
                    risk_level=rl,
                    static_candidates=agents,
                    max_agents=MAX_AGENTS_PER_MISSION,
                )
            except Exception as _dr_err:
                log.debug("dynamic_routing_skipped", err=str(_dr_err)[:60])
            # ── end dynamic routing ──────────────────────────────────────

            # ── Multimodal routing overlay (fail-open) ───────────────────
            try:
                from core.dynamic_agent_router import detect_multimodal_type, get_multimodal_agents
                _modal = detect_multimodal_type(goal)
                if _modal:
                    _modal_agents = get_multimodal_agents(_modal)
                    for _ma in _modal_agents:
                        if _ma not in agents:
                            agents.append(_ma)
                    log.info("multimodal_routing", type=_modal, agents=agents)
            except Exception as _exc:
                log.warning("swallowed_exception", action="multimodal_routing_inject", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            # ── end multimodal routing ───────────────────────────────────

            # Capability registry filter (fail-open, ≥10 entries)
            try:
                from memory.capability_registry import CapabilityRegistry
                from memory.decision_memory import get_decision_memory
                _dm = get_decision_memory()
                if len(_dm._entries) >= 10:
                    _reg = CapabilityRegistry()
                    _reg.build_from_memory(_dm)
                    _f = [
                        a for a in agents
                        if _reg.score_agent_for_context(a, mission_type, cx) >= 0.3
                    ]
                    if _f:
                        agents = _f
            except Exception as _exc:
                log.warning("swallowed_exception", action="specialization_filter", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            agents = self._ensure_file_builder(agents, g)
            log.info(
                "agent_selector_mission_routing",
                agents=agents, mission_type=mission_type,
                complexity=cx, risk=risk_level, count=len(agents),
            )
            return agents

        # ── LOW → 1 agent strict ──────────────────────────────────────────────
        if cx == "low":
            agent = "forge-builder" if ("code" in g or "### fichier" in g) else "scout-research"
            log.info(
                "agent_selector_v1",
                agents=[agent], goal=goal[:60], risk=risk_level,
                domain=domain, count=1, complexity=cx,
            )
            return [agent]

        # ── MEDIUM → 2-3 agents ───────────────────────────────────────────────
        if cx == "medium":
            agents = ["scout-research", "lens-reviewer"]
            if rl in ("MEDIUM", "HIGH"):
                agents.append("shadow-advisor")
            agents = self._ensure_file_builder(agents, g)
            log.info(
                "agent_selector_v1",
                agents=agents, goal=goal[:60], risk=risk_level,
                domain=domain, count=len(agents), complexity=cx,
            )
            return agents

        # ── HIGH → logique complète (map-planner conditionnel) ────────────────
        # Base : lens-reviewer toujours, map-planner uniquement si mots planning
        agents: list[str] = ["lens-reviewer"]
        if any(kw in g for kw in self._PLANNING_KW):
            agents.insert(0, "map-planner")

        # Si un profil de domaine est fourni, utiliser ses agents préférés comme guide
        if preferred_agents:
            domain_set = preferred_agents
        else:
            domain_set = DOMAIN_AGENT_PROFILES.get(domain, DOMAIN_AGENT_PROFILES["general"])

        # scout-research : mots-clés recherche/analyse
        if any(kw in g for kw in self._RESEARCH_KW) or "scout-research" in domain_set:
            if "scout-research" not in agents:
                agents.insert(0, "scout-research")

        # shadow-advisor : MEDIUM/HIGH risk OU mots-clés sensibles
        if rl in ("MEDIUM", "HIGH") or any(kw in g for kw in self._RISK_KW):
            if "shadow-advisor" not in agents:
                agents.append("shadow-advisor")

        # forge-builder : mots-clés code/construction (indépendant du domaine)
        if any(kw in g for kw in self._CODE_KW):
            if "forge-builder" not in agents:
                agents.append("forge-builder")

        # vault-memory : mots-clés mémoire/historique
        if any(kw in g for kw in self._MEMORY_KW):
            if "vault-memory" not in agents:
                agents.insert(0, "vault-memory")

        # pulse-ops : mots-clés ops/monitoring
        if any(kw in g for kw in self._OPS_KW):
            if "pulse-ops" not in agents:
                agents.append("pulse-ops")

        # Cap strict MAX_AGENTS_PER_MISSION
        # Priorité de conservation : map-planner, lens-reviewer, shadow-advisor, scout-research, forge-builder, vault-memory, pulse-ops
        _priority_order = [
            "map-planner", "lens-reviewer", "shadow-advisor",
            "scout-research", "forge-builder", "vault-memory", "pulse-ops",
        ]
        if len(agents) > MAX_AGENTS_PER_MISSION:
            # Garder dans l'ordre de priorité
            kept = []
            for p in _priority_order:
                if p in agents and len(kept) < MAX_AGENTS_PER_MISSION:
                    kept.append(p)
            agents = kept

        log.info(
            "agent_selector_v1",
            agents=agents,
            goal=goal[:60],
            risk=risk_level,
            domain=domain,
            count=len(agents),
        )
        try:
            from memory.decision_memory import get_decision_memory, classify_mission_type
            agents = get_decision_memory().suggest_agents(
                classify_mission_type(goal, complexity), complexity, agents,
            )
        except Exception as _exc:
            log.warning("swallowed_exception", action="decision_memory_suggest", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # ── Capability registry filter (fail-open, < 1ms) ────────────────────
        try:
            from memory.capability_registry import CapabilityRegistry
            from memory.decision_memory import get_decision_memory, classify_mission_type
            _dm = get_decision_memory()
            if len(_dm._entries) >= 10:
                _reg = CapabilityRegistry()
                _reg.build_from_memory(_dm)
                _mtype = classify_mission_type(goal, complexity)

                _filtered = [
                    a for a in agents
                    if _reg.score_agent_for_context(a, _mtype, complexity) >= 0.3
                ]
                if _filtered:
                    agents = _filtered

                if complexity != "low" and len(agents) < MAX_AGENTS_PER_MISSION:
                    _recommended = _reg.get_recommended_agents(_mtype, complexity, 1)
                    for _rec in _recommended:
                        if _rec not in agents and len(agents) < MAX_AGENTS_PER_MISSION:
                            agents.append(_rec)
        except Exception as _exc:
            log.warning("swallowed_exception", action="agent_specialization_apply", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # ── PolicyMode apply ─────────────────────────────────────────────────
        try:
            if _pm == "SAFE":
                # Force 1 agent max, jamais shadow/planner
                safe_filter = [a for a in agents if a not in ("shadow-advisor", "map-planner")]
                agents = safe_filter[:1] if safe_filter else agents[:1]
            elif _pm == "UNCENSORED" and complexity != "low":
                # Boost exploration : ajoute lens-reviewer + map-planner si pas présents et pas info_query
                from memory.decision_memory import classify_mission_type
                _mt = mission_type if mission_type else ""
                if _mt not in ("info_query", "compare_query", "planning_task"):
                    if "lens-reviewer" not in agents and len(agents) < 4:
                        agents = agents + ["lens-reviewer"]
                    if "map-planner" not in agents and len(agents) < 5 and complexity == "high":
                        agents = agents + ["map-planner"]
        except Exception as _exc:
            log.warning("swallowed_exception", action="policymode_inject", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        # ── end PolicyMode apply ─────────────────────────────────────────────

        return self._ensure_file_builder(agents, g)


_selector_instance: AgentSelector | None = None


def get_agent_selector() -> AgentSelector:
    global _selector_instance
    if _selector_instance is None:
        _selector_instance = AgentSelector()
    return _selector_instance


def select_agents(
    goal: str,
    risk_level: str = "LOW",
    domain: str = "general",
    complexity: str = "medium",
    *,
    mission_type: str = "",
) -> list[str]:
    """Module-level convenience wrapper around AgentSelector.select_agents()."""
    return get_agent_selector().select_agents(
        goal,
        risk_level=risk_level,
        domain=domain,
        mission_type=mission_type,
        complexity=complexity,
    )
