"""
BEA MAX — Capability Registry
Registry léger calculé depuis decision_memory. Pas de persistence propre —
reconstruit à la demande depuis decision_memory.jsonl. O(n) sur max 1000 entrées.
stdlib uniquement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.decision_memory import DecisionMemory

# Score neutre pour agents sans historique
_NEUTRAL_SCORE = 0.5

# Agents naturellement adaptés à chaque mission_type (boost +0.05)
_NATURAL_FIT: dict[str, list[str]] = {
    "coding_task":       ["forge-builder"],
    "debug_task":        ["forge-builder", "lens-reviewer"],
    "architecture_task": ["map-planner", "lens-reviewer"],
    "system_task":       ["pulse-ops"],
    "planning_task":     ["map-planner"],
    "research_task":     ["scout-research"],
    "info_query":        ["scout-research"],
    "evaluation_task":   ["lens-reviewer"],
}
# Seuil minimum pour inclure un agent dans les recommandations
_MIN_SCORE     = 0.3
# Seuil "éviter" : success_rate < X pour ce pattern → avoid_for
_AVOID_THRESHOLD = 0.4
# Seuil "recommandé" : success_rate > X → recommended_for
_RECOMMEND_THRESHOLD = 0.7


@dataclass
class AgentCapabilityScore:
    agent_name:      str
    mission_types:   list[str]  # types de missions où cet agent est utilisé
    success_rate:    float      # taux de succès pondéré (0.0-1.0)
    avg_confidence:  float      # confiance moyenne des missions où il apparaît
    call_count:      int        # nombre de fois utilisé en prod
    last_seen:       int        # unix timestamp
    recommended_for: list[str]  # ["low/analysis", "medium/code", ...]
    avoid_for:       list[str]  # patterns avec success_rate < 0.4
    tool_affinity:   dict       = field(default_factory=dict)  # {tool_name: success_rate}

    def overall_score(self) -> float:
        return 0.7 * self.success_rate + 0.3 * self.avg_confidence


class CapabilityRegistry:
    """Registry léger calculé depuis decision_memory.

    Utilisation :
        reg = CapabilityRegistry()
        reg.build_from_memory(get_decision_memory())
        score = reg.score_agent_for_context("scout-research", "analysis", "medium")
    """

    def __init__(self) -> None:
        self._scores: dict[str, AgentCapabilityScore] = {}

    # ── Construction ──────────────────────────────────────────────────────────

    def build_from_memory(self, memory: "DecisionMemory") -> dict[str, AgentCapabilityScore]:
        """Agrège les scores par agent depuis les DecisionOutcomes.
        Pour chaque entrée : pour chaque agent dans selected_agents,
        accumuler (success, confidence, mission_type). O(n × avg_agents)."""
        # Accumulateurs : agent → {pattern_key → [successes, total]}
        # pattern_key = "mission_type/complexity"
        acc: dict[str, dict] = {}

        for entry in memory._entries:
            agents     = entry.get("selected_agents", [])
            success    = entry.get("success", False)
            confidence = entry.get("confidence_score", 0.5)
            mtype      = entry.get("mission_type", "unknown")
            complexity = entry.get("complexity", "medium")
            ts         = entry.get("ts", 0)
            pattern    = f"{complexity}/{mtype}"

            for agent in agents:
                if agent not in acc:
                    acc[agent] = {
                        "patterns":    {},   # pattern → [success_count, total]
                        "conf_sum":    0.0,
                        "total":       0,
                        "last_seen":   0,
                        "mtypes":      set(),
                    }
                a = acc[agent]
                if pattern not in a["patterns"]:
                    a["patterns"][pattern] = [0, 0]
                if success:
                    a["patterns"][pattern][0] += 1
                a["patterns"][pattern][1] += 1
                a["conf_sum"]  += confidence
                a["total"]     += 1
                a["last_seen"]  = max(a["last_seen"], ts)
                a["mtypes"].add(mtype)

        scores: dict[str, AgentCapabilityScore] = {}
        for agent, a in acc.items():
            total = a["total"]
            if total == 0:
                continue

            # success_rate global
            total_success = sum(v[0] for v in a["patterns"].values())
            global_sr = total_success / total

            # recommended_for / avoid_for par pattern
            recommended_for: list[str] = []
            avoid_for: list[str]       = []
            for pat, (succ, tot) in a["patterns"].items():
                if tot < 2:
                    continue
                sr = succ / tot
                if sr >= _RECOMMEND_THRESHOLD:
                    recommended_for.append(pat)
                elif sr < _AVOID_THRESHOLD:
                    avoid_for.append(pat)

            scores[agent] = AgentCapabilityScore(
                agent_name      = agent,
                mission_types   = sorted(a["mtypes"]),
                success_rate    = round(global_sr, 3),
                avg_confidence  = round(a["conf_sum"] / total, 3),
                call_count      = total,
                last_seen       = a["last_seen"],
                recommended_for = recommended_for,
                avoid_for       = avoid_for,
                tool_affinity   = {},  # enrichi au runtime par ToolExecutor
            )

        self._scores = scores
        return scores

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score_agent_for_context(self, agent: str, mission_type: str, complexity: str, required_tools: list = None) -> float:
        """Score 0.0-1.0 pour un agent dans un contexte donné.
        - Si agent jamais vu → score neutre 0.5 (+ +0.05 si natural fit)
        - Si dans avoid_for pour ce pattern → 0.2
        - Si success_rate > 0.7 pour ce pattern → score élevé
        - Sinon : success_rate pondéré × avg_confidence
        - +0.05 bonus si agent est un natural fit pour ce mission_type"""
        cap = self._scores.get(agent)
        _natural_fit = agent in _NATURAL_FIT.get(mission_type, [])

        if cap is None:
            base = round(min(1.0, _NEUTRAL_SCORE + 0.05), 3) if _natural_fit else _NEUTRAL_SCORE
            return base

        pattern = f"{complexity}/{mission_type}"

        if pattern in cap.avoid_for:
            return 0.2

        if pattern in cap.recommended_for:
            score = round(min(1.0, cap.success_rate * 1.1 + cap.avg_confidence * 0.1), 3)
        else:
            score = round(min(1.0, cap.success_rate * 0.8 + cap.avg_confidence * 0.2), 3)

        if _natural_fit:
            score = round(min(1.0, score + 0.05), 3)

        # Bonus tool_affinity si required_tools fourni
        if required_tools and cap is not None and cap.tool_affinity:
            for tool in required_tools:
                affinity = cap.tool_affinity.get(tool, None)
                if affinity is not None and affinity > 0.6:
                    score = round(min(1.0, score + 0.08), 3)
                    break  # un seul bonus max

        return score

    # ── Recommandation ────────────────────────────────────────────────────────

    def get_recommended_agents(
        self,
        mission_type: str,
        complexity: str,
        max_agents: int,
    ) -> list[str]:
        """Retourne les N meilleurs agents pour ce contexte (score > 0.3), triés."""
        scored = [
            (agent, self.score_agent_for_context(agent, mission_type, complexity))
            for agent in self._scores
        ]
        filtered = [(a, s) for a, s in scored if s > _MIN_SCORE]
        filtered.sort(key=lambda x: -x[1])
        return [a for a, _ in filtered[:max_agents]]

    # ── Résumé API ────────────────────────────────────────────────────────────

    def get_registry_summary(self) -> dict:
        """Pour l'API : dict compact avec scores et recommandations."""
        return {
            agent: {
                "success_rate":    cap.success_rate,
                "avg_confidence":  cap.avg_confidence,
                "call_count":      cap.call_count,
                "mission_types":   cap.mission_types,
                "recommended_for": cap.recommended_for,
                "avoid_for":       cap.avoid_for,
                "last_seen":       cap.last_seen,
            }
            for agent, cap in self._scores.items()
        }

    # ── RAM estimate ──────────────────────────────────────────────────────────

    def ram_kb(self) -> float:
        """~200 bytes/agent, 10 agents max → ~2 KB."""
        return round(len(self._scores) * 200 / 1024, 1)
