"""
WeaknessDetector — analyses capability scores and failure patterns to identify
domains where JarvisMax performs poorly.

Returns List[Weakness] sorted by severity (HIGH first).
Works with no historical data (returns [] or LOW-severity results).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger("jarvis.self_improvement.weakness_detector")

# Severity thresholds for capability score success_rate
_HIGH_THRESHOLD = 0.5     # success_rate < 0.5  → HIGH
_MEDIUM_THRESHOLD = 0.65  # success_rate < 0.65 → MEDIUM

DOMAINS = ["coding", "api_usage", "debugging", "automation", "planning", "research"]

_SEVERITY_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class Weakness:
    domain: str
    severity: str           # LOW / MEDIUM / HIGH
    evidence: List[str] = field(default_factory=list)
    suggested_focus: str = ""


class WeaknessDetector:
    """
    Detects weaknesses across three sources:
      1. Capability scorer domain scores
      2. Knowledge pattern detector failure rates
      3. Tool registry high-risk tool inventory
    """

    def detect(self) -> List[Weakness]:
        """
        Returns deduplicated list of Weakness sorted by severity descending.
        Fail-open: never raises.
        """
        weaknesses: List[Weakness] = []

        weaknesses += self._detect_from_capability_scores()
        weaknesses += self._detect_from_knowledge_patterns()
        weaknesses += self._detect_from_tool_errors()

        # Deduplicate by domain — keep highest severity
        seen: dict[str, Weakness] = {}
        for w in weaknesses:
            if w.domain not in seen:
                seen[w.domain] = w
            elif _SEVERITY_ORDER.get(w.severity, 0) > _SEVERITY_ORDER.get(seen[w.domain].severity, 0):
                seen[w.domain] = w

        return sorted(
            seen.values(),
            key=lambda x: _SEVERITY_ORDER.get(x.severity, 0),
            reverse=True,
        )

    # ── Source 1: Capability Scorer ───────────────────────────────────────────

    def _detect_from_capability_scores(self) -> List[Weakness]:
        result = []
        try:
            from core.knowledge.capability_scorer import get_capability_scorer
            scorer = get_capability_scorer()
            stats = scorer.get_stats()

            for domain, info in stats.items():
                if not isinstance(info, dict):
                    continue
                sr = info.get("success_rate", 0.5)
                total = info.get("total_tasks", 0)
                if total == 0:
                    continue

                evidence = [
                    f"success_rate={sr:.2f}",
                    f"total_tasks={total}",
                    f"avg_errors={info.get('avg_errors', 0):.2f}",
                ]

                if sr < _HIGH_THRESHOLD:
                    severity = "HIGH"
                    focus = (
                        f"Critical weakness in {domain}: success rate {sr:.0%}. "
                        f"Focus on improving {domain} task patterns and error recovery."
                    )
                elif sr < _MEDIUM_THRESHOLD:
                    severity = "MEDIUM"
                    focus = (
                        f"Moderate weakness in {domain}: success rate {sr:.0%}. "
                        f"Review common failure patterns and retry strategies."
                    )
                else:
                    continue  # healthy domain

                result.append(Weakness(
                    domain=domain,
                    severity=severity,
                    evidence=evidence,
                    suggested_focus=focus,
                ))
        except Exception as e:
            logger.debug(f"_detect_from_capability_scores error: {e}")
        return result

    # ── Source 2: Knowledge Pattern Detector ─────────────────────────────────

    def _detect_from_knowledge_patterns(self) -> List[Weakness]:
        result = []
        try:
            from core.knowledge.pattern_detector import detect_patterns

            for domain in DOMAINS:
                try:
                    patterns = detect_patterns(
                        goal=f"task in {domain}", mission_type=domain
                    )
                    failure_rate = patterns.get("failure_rate", 0.0)
                    prior_failures = patterns.get("prior_failures", 0)

                    if prior_failures >= 3 and failure_rate > 0.5:
                        severity = "HIGH" if failure_rate > 0.7 else "MEDIUM"
                        result.append(Weakness(
                            domain=domain,
                            severity=severity,
                            evidence=[
                                f"failure_rate={failure_rate:.2f}",
                                f"prior_failures={prior_failures}",
                            ],
                            suggested_focus=(
                                f"Repeated failures ({prior_failures}) in {domain}. "
                                f"Review task strategy and tool selection."
                            ),
                        ))
                except Exception:
                    _silent_log.debug("suppressed_exception", src='weakness_detector.py')
        except Exception as e:
            logger.debug(f"_detect_from_knowledge_patterns error: {e}")
        return result

    # ── Source 3: Tool Registry High-Risk Inventory ───────────────────────────

    def _detect_from_tool_errors(self) -> List[Weakness]:
        result = []
        try:
            from core.tool_registry import get_tool_registry
            registry = get_tool_registry()
            tools = registry.list_tools()

            high_risk = [
                t.get("name", "") for t in tools
                if t.get("action_type", "") in ("execute", "external_api")
                and t.get("name", "")
            ]

            if high_risk:
                result.append(Weakness(
                    domain="api_usage",
                    severity="LOW",
                    evidence=[f"high_risk_tools={','.join(high_risk[:3])}"],
                    suggested_focus=(
                        "Monitor high-risk tools (execute/external_api) "
                        "for error patterns. Consider adding retry strategies."
                    ),
                ))
        except Exception as e:
            logger.debug(f"_detect_from_tool_errors error: {e}")
        return result


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: WeaknessDetector | None = None


def get_weakness_detector() -> WeaknessDetector:
    global _detector
    if _detector is None:
        _detector = WeaknessDetector()
    return _detector
