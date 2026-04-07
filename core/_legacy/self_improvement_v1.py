"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  DEAD MODULE — SHADOWED BY PACKAGE                                          ║
║                                                                              ║
║  This file (core/self_improvement.py) is PERMANENTLY SHADOWED at runtime   ║
║  by the package core/self_improvement/ (directory with __init__.py).        ║
║  Python resolves the PACKAGE, not this file.                                ║
║                                                                              ║
║  Any `from core.self_improvement import *` resolves to:                     ║
║    core/self_improvement/__init__.py  ← this is what runs                  ║
║                                                                              ║
║  This file is UNREACHABLE via normal imports. Do NOT add code here.         ║
║  Its SelfImprovementManager is re-exposed via __init__.py for compatibility.║
║                                                                              ║
║  MIGRATION STATUS:                                                           ║
║    - get_self_improvement_manager() → re-exposed in __init__.py             ║
║    - SelfImprovementManager.analyze_patterns() → use SelfImprovementEngine  ║
║    - Canonical V3 pipeline → core/self_improvement/engine.py               ║
║                                                                              ║
║  NEXT STEP: once callers are migrated to SelfImprovementEngine,             ║
║  delete this file entirely.                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class SelfImprovementSuggestion:
    problem_type: str          # ex. "high_fallback_rate", "low_confidence", "over_approval"
    mission_type: str          # ex. "coding_task"
    frequency: int             # nombre d'occurrences observées
    confidence_avg: float      # moyenne confidence_score pour ce pattern
    impact_estimate: str       # "low" | "medium" | "high"
    risk_estimate: str         # "low" | "medium" | "high"
    suggested_change: str      # description textuelle de l'amélioration proposée
    affected_files: List[str]  # fichiers concernés (jamais modifiés automatiquement)
    priority_score: float      # calculé = freq_w + impact_w - risk_w


# Poids pour priority_score
_FREQ_WEIGHT = 0.4
_IMPACT_WEIGHT = {"low": 0.1, "medium": 0.3, "high": 0.5}
_RISK_WEIGHT   = {"low": 0.0, "medium": 0.1, "high": 0.3}

def _priority(freq: int, impact: str, risk: str) -> float:
    freq_norm = min(freq / 20.0, 1.0)  # normalise sur 20 occurrences max
    return round(
        freq_norm * _FREQ_WEIGHT
        + _IMPACT_WEIGHT.get(impact, 0.3)
        - _RISK_WEIGHT.get(risk, 0.1),
        3
    )


class SelfImprovementManager:
    """
    Analyse les patterns de decision_memory et capability_registry.
    Ne produit que des suggestions — ne modifie jamais de fichier.
    """

    def analyze_patterns(self) -> List[SelfImprovementSuggestion]:
        """
        Scan les entrées de DecisionMemory, détecte 7 patterns,
        retourne au max 5 suggestions triées par priority_score desc.
        """
        start = time.monotonic()
        suggestions: List[SelfImprovementSuggestion] = []
        try:
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            entries = list(dm._entries)
            if not entries:
                return []

            suggestions += self._detect_high_fallback(entries)
            suggestions += self._detect_low_confidence(entries)
            suggestions += self._detect_weak_agent(entries)
            suggestions += self._detect_over_approval(entries)
            suggestions += self._detect_high_latency(entries)
            suggestions += self._detect_agent_avoidance(entries)
            suggestions += self._detect_agent_overuse(entries)

            # Déduplique par problem_type+mission_type, garde le plus fréquent
            seen = {}
            for s in suggestions:
                key = f"{s.problem_type}:{s.mission_type}"
                if key not in seen or s.frequency > seen[key].frequency:
                    seen[key] = s

            result = sorted(seen.values(), key=lambda x: x.priority_score, reverse=True)[:5]
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug(f"[SelfImprovement] analyze_patterns: {len(result)} suggestions in {elapsed_ms:.1f}ms")
            return result

        except Exception as e:
            logger.warning(f"[SelfImprovementManager] analyze_patterns error: {e}")
            return []

    # ── Pattern detectors ──────────────────────────────────────────────────

    def _detect_high_fallback(self, entries) -> List[SelfImprovementSuggestion]:
        """Missions avec fallback_level >= 2 trop fréquentes par mission_type."""
        from collections import Counter
        counts: Counter = Counter()
        total: Counter = Counter()
        for e in entries:
            mt = getattr(e, "mission_type", "unknown")
            total[mt] += 1
            if getattr(e, "fallback_level_used", 0) >= 2:
                counts[mt] += 1
        result = []
        for mt, cnt in counts.items():
            if total[mt] >= 5 and cnt / total[mt] >= 0.3:
                result.append(SelfImprovementSuggestion(
                    problem_type="high_fallback_rate",
                    mission_type=mt,
                    frequency=cnt,
                    confidence_avg=self._avg_confidence(entries, mt),
                    impact_estimate="high",
                    risk_estimate="low",
                    suggested_change=f"Améliorer la sélection d'agents pour '{mt}' — taux fallback >= 2 : {cnt}/{total[mt]}",
                    affected_files=["agents/crew.py"],
                    priority_score=_priority(cnt, "high", "low"),
                ))
        return result

    def _detect_low_confidence(self, entries) -> List[SelfImprovementSuggestion]:
        """confidence_score moyen < 0.6 pour un mission_type."""
        from collections import defaultdict
        scores = defaultdict(list)
        for e in entries:
            mt = getattr(e, "mission_type", "unknown")
            scores[mt].append(getattr(e, "confidence_score", 0.5))
        result = []
        for mt, sc in scores.items():
            if len(sc) >= 5:
                avg = sum(sc) / len(sc)
                if avg < 0.6:
                    result.append(SelfImprovementSuggestion(
                        problem_type="low_confidence",
                        mission_type=mt,
                        frequency=len(sc),
                        confidence_avg=round(avg, 3),
                        impact_estimate="medium",
                        risk_estimate="low",
                        suggested_change=f"Confiance moyenne faible ({avg:.2f}) pour '{mt}' — revoir routing ou ajouter lens-reviewer",
                        affected_files=["agents/crew.py", "core/mission_system.py"],
                        priority_score=_priority(len(sc), "medium", "low"),
                    ))
        return result

    def _detect_weak_agent(self, entries) -> List[SelfImprovementSuggestion]:
        """Agent souvent sélectionné mais success_rate faible (via capability_registry)."""
        result = []
        try:
            from memory.capability_registry import get_capability_registry
            from memory.decision_memory import get_decision_memory
            dm = get_decision_memory()
            if len(dm._entries) < 10:
                return []
            reg = get_capability_registry()
            scores = reg.build_from_memory(dm)
            for agent, s in scores.items():
                if s.call_count >= 5 and s.success_rate < 0.5:
                    result.append(SelfImprovementSuggestion(
                        problem_type="weak_agent_performance",
                        mission_type="all",
                        frequency=s.call_count,
                        confidence_avg=s.avg_confidence,
                        impact_estimate="medium",
                        risk_estimate="medium",
                        suggested_change=f"Agent '{agent}' — success_rate {s.success_rate:.0%} sur {s.call_count} appels. Envisager de réduire son usage ou ajuster ses instructions.",
                        affected_files=["agents/crew.py"],
                        priority_score=_priority(s.call_count, "medium", "medium"),
                    ))
        except Exception:
            pass
        return result

    def _detect_over_approval(self, entries) -> List[SelfImprovementSuggestion]:
        """Missions SUPERVISED/AUTO nécessitant approval de façon répétée sans raison (risk <= 3)."""
        from collections import Counter
        counts: Counter = Counter()
        total: Counter = Counter()
        for e in entries:
            mt = getattr(e, "mission_type", "unknown")
            mode = getattr(e, "approval_mode", "")
            decision = getattr(e, "approval_decision", "")
            risk = getattr(e, "risk_score", 5)
            if mode in ("SUPERVISED", "AUTO") and risk <= 3:
                total[mt] += 1
                if decision == "manual":
                    counts[mt] += 1
        result = []
        for mt, cnt in counts.items():
            if total[mt] >= 5 and cnt / total[mt] >= 0.4:
                result.append(SelfImprovementSuggestion(
                    problem_type="over_approval",
                    mission_type=mt,
                    frequency=cnt,
                    confidence_avg=self._avg_confidence(entries, mt),
                    impact_estimate="medium",
                    risk_estimate="low",
                    suggested_change=f"Trop d'approbations manuelles pour '{mt}' (risk <= 3) — vérifier evaluate_approval() pour ce type",
                    affected_files=["core/mission_system.py"],
                    priority_score=_priority(cnt, "medium", "low"),
                ))
        return result

    def _detect_high_latency(self, entries) -> List[SelfImprovementSuggestion]:
        """Latence élevée (>= 30s) fréquente pour un mission_type."""
        from collections import defaultdict
        latencies = defaultdict(list)
        for e in entries:
            mt = getattr(e, "mission_type", "unknown")
            lat = getattr(e, "latency_ms", 0)
            if lat > 0:
                latencies[mt].append(lat)
        result = []
        for mt, lats in latencies.items():
            if len(lats) >= 5:
                avg = sum(lats) / len(lats)
                high = sum(1 for l in lats if l >= 30000)
                if high / len(lats) >= 0.3:
                    result.append(SelfImprovementSuggestion(
                        problem_type="high_latency",
                        mission_type=mt,
                        frequency=high,
                        confidence_avg=self._avg_confidence(entries, mt),
                        impact_estimate="medium",
                        risk_estimate="low",
                        suggested_change=f"Latence élevée pour '{mt}' — avg {avg/1000:.1f}s. Réduire nombre d'agents ou vérifier timeout ollama.",
                        affected_files=["agents/crew.py"],
                        priority_score=_priority(high, "medium", "low"),
                    ))
        return result

    def _detect_agent_avoidance(self, entries) -> List[SelfImprovementSuggestion]:
        """Agent jamais sélectionné pour un mission_type malgré routing favorable."""
        from collections import defaultdict
        ROUTING = {
            "coding_task": ["forge-builder"],
            "debug_task": ["forge-builder", "lens-reviewer"],
            "system_task": ["pulse-ops"],
            "planning_task": ["map-planner"],
        }
        mt_counts = defaultdict(int)
        agent_mt_counts = defaultdict(lambda: defaultdict(int))
        for e in entries:
            mt = getattr(e, "mission_type", "unknown")
            mt_counts[mt] += 1
            for ag in getattr(e, "selected_agents", []):
                agent_mt_counts[mt][ag] += 1
        result = []
        for mt, expected_agents in ROUTING.items():
            if mt_counts[mt] < 10:
                continue
            for agent in expected_agents:
                usage = agent_mt_counts[mt].get(agent, 0)
                if usage == 0:
                    result.append(SelfImprovementSuggestion(
                        problem_type="agent_never_used",
                        mission_type=mt,
                        frequency=mt_counts[mt],
                        confidence_avg=self._avg_confidence(entries, mt),
                        impact_estimate="low",
                        risk_estimate="low",
                        suggested_change=f"Agent '{agent}' jamais utilisé pour '{mt}' sur {mt_counts[mt]} missions — vérifier capability_registry filter trop restrictif.",
                        affected_files=["agents/crew.py", "memory/capability_registry.py"],
                        priority_score=_priority(mt_counts[mt], "low", "low"),
                    ))
        return result

    def _detect_agent_overuse(self, entries) -> List[SelfImprovementSuggestion]:
        """Agent lourd (map-planner/shadow-advisor) sur-utilisé pour missions low."""
        heavy = {"map-planner", "shadow-advisor", "lens-reviewer"}
        count = 0
        for e in entries:
            cx = getattr(e, "complexity", "medium")
            if cx == "low":
                agents = getattr(e, "selected_agents", [])
                if any(a in heavy for a in agents):
                    count += 1
        if count >= 5:
            return [SelfImprovementSuggestion(
                problem_type="agent_overuse_low_complexity",
                mission_type="any_low",
                frequency=count,
                confidence_avg=0.0,
                impact_estimate="medium",
                risk_estimate="low",
                suggested_change=f"Agents lourds ({', '.join(heavy)}) utilisés {count}x sur missions low complexity — renforcer règle max_1_agent_low dans select_agents().",
                affected_files=["agents/crew.py"],
                priority_score=_priority(count, "medium", "low"),
            )]
        return []

    def _avg_confidence(self, entries, mission_type: str) -> float:
        vals = [getattr(e, "confidence_score", 0.5) for e in entries
                if getattr(e, "mission_type", "") == mission_type]
        return round(sum(vals) / len(vals), 3) if vals else 0.5


# Singleton
_manager: Optional[SelfImprovementManager] = None

def get_self_improvement_manager() -> SelfImprovementManager:
    global _manager
    if _manager is None:
        _manager = SelfImprovementManager()
    return _manager
