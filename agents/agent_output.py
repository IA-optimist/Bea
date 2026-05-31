"""
JARVIS MAX — AgentOutput
Structure de sortie standardisée pour tous les agents.

Contrat uniforme exposable par l'API :
  - AgentOutput         : dataclass principale (from_raw + from_agent_result)
  - AgentOutputBuilder  : builder fluent pour construire un output étape par étape
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentOutput:
    """Sortie normalisée d'un agent — V1 standardisé."""
    reasoning:    str
    decision:     str
    confidence:   float           # 0.0–1.0
    risks:        list[str]       = field(default_factory=list)
    next_actions: list[str]       = field(default_factory=list)
    raw:          str             = ""

    # Champs V1 standardisés
    agent_name:        str        = ""
    action:            str        = ""    # analyzed / planned / built / reviewed
    result:            str        = ""    # output tronqué 2000 chars
    risk_score:        int        = 0     # 0-10
    execution_time_ms: int        = 0
    success:           bool       = True
    error:             str | None = None

    def to_dict(self) -> dict:
        return {
            "reasoning":         self.reasoning[:200],
            "decision":          self.decision,
            "confidence":        self.confidence,
            "risks":             self.risks,
            "next_actions":      self.next_actions,
            "raw":               self.raw[:500],
            # V1
            "agent_name":        self.agent_name,
            "action":            self.action,
            "result":            self.result[:2000],
            "risk_score":        self.risk_score,
            "execution_time_ms": self.execution_time_ms,
            "success":           self.success,
            "error":             self.error,
        }

    @classmethod
    def from_raw(cls, raw: str, agent_name: str = "", execution_time_ms: int = 0) -> "AgentOutput":
        """
        Parse JSON structuré ou best-effort depuis string brute.

        Si le JSON contient reasoning/decision/confidence → utilise les champs.
        Sinon, traite le tout comme reasoning brut.
        """
        if not raw:
            return cls(
                reasoning="", decision="", confidence=0.0, raw=raw,
                agent_name=agent_name, execution_time_ms=execution_time_ms,
                result="", success=False,
            )

        # Tentative JSON
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                reasoning = (
                    parsed.get("reasoning")
                    or parsed.get("justification")
                    or parsed.get("analysis")
                    or ""
                )
                decision = (
                    parsed.get("decision")
                    or parsed.get("verdict")
                    or parsed.get("action")
                    or ""
                )
                conf_raw = parsed.get("confidence") or parsed.get("score") or 0.0
                try:
                    confidence = float(conf_raw)
                    # Normalise scores /10 → /1
                    if confidence > 1.0:
                        confidence = confidence / 10.0
                    confidence = max(0.0, min(1.0, confidence))
                except (TypeError, ValueError):
                    confidence = 0.0

                risks = parsed.get("risks") or parsed.get("issues") or []
                if not isinstance(risks, list):
                    risks = [str(risks)]
                risks = [str(r) for r in risks]

                suggestions = (
                    parsed.get("suggestions")
                    or parsed.get("improvements")
                    or parsed.get("next_actions")
                    or []
                )
                if not isinstance(suggestions, list):
                    suggestions = [str(suggestions)]
                suggestions = [str(s) for s in suggestions]

                # Si reasoning ou decision vides mais le JSON contient du texte, fallback
                if not reasoning and not decision:
                    reasoning = raw[:500]

                # action: infer from decision or agent_name
                action = parsed.get("action_type") or parsed.get("action") or ""
                if not action and agent_name:
                    _action_map = {
                        "scout-research": "analyzed", "map-planner": "planned",
                        "forge-builder": "built", "lens-reviewer": "reviewed",
                        "shadow-advisor": "analyzed", "vault-memory": "retrieved",
                        "pulse-ops": "monitored",
                    }
                    action = _action_map.get(agent_name, "processed")

                return cls(
                    reasoning=str(reasoning)[:200],
                    decision=str(decision)[:500],
                    confidence=confidence,
                    risks=risks[:10],
                    next_actions=suggestions[:10],
                    raw=raw,
                    agent_name=agent_name,
                    action=action,
                    result=str(decision or reasoning)[:2000],
                    execution_time_ms=execution_time_ms,
                    success=True,
                )
        except (json.JSONDecodeError, Exception) as _exc:
            log.warning("swallowed_exception", action="agent_output_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Fallback brut
        action_fb = ""
        if agent_name:
            _action_map = {
                "scout-research": "analyzed", "map-planner": "planned",
                "forge-builder": "built", "lens-reviewer": "reviewed",
                "shadow-advisor": "analyzed", "vault-memory": "retrieved",
                "pulse-ops": "monitored",
            }
            action_fb = _action_map.get(agent_name, "processed")
        return cls(
            reasoning=raw[:200],
            decision="",
            confidence=0.0,
            risks=[],
            next_actions=[],
            raw=raw,
            agent_name=agent_name,
            action=action_fb,
            result=raw[:2000],
            execution_time_ms=execution_time_ms,
            success=bool(raw),
        )

    @classmethod
    def from_agent_result(cls, result: Any) -> "AgentOutput":
        """
        Convertit un AgentResult (parallel_executor) en AgentOutput.
        Rétrocompatible avec l'existant.
        """
        output = getattr(result, "output", "") or ""
        return cls.from_raw(output)


class AgentOutputBuilder:
    """Builder fluent pour construire un AgentOutput étape par étape."""

    def __init__(self) -> None:
        self._reasoning = ""
        self._decision  = ""
        self._conf      = 0.0
        self._risks: list[str] = []
        self._actions: list[str] = []
        self._raw = ""

    def reasoning(self, text: str) -> "AgentOutputBuilder":
        self._reasoning = text
        return self

    def decision(self, text: str) -> "AgentOutputBuilder":
        self._decision = text
        return self

    def confidence(self, score: float) -> "AgentOutputBuilder":
        self._conf = max(0.0, min(1.0, float(score)))
        return self

    def risk(self, r: str) -> "AgentOutputBuilder":
        self._risks.append(r)
        return self

    def action(self, a: str) -> "AgentOutputBuilder":
        self._actions.append(a)
        return self

    def raw(self, text: str) -> "AgentOutputBuilder":
        self._raw = text
        return self

    def build(self) -> AgentOutput:
        return AgentOutput(
            reasoning=self._reasoning,
            decision=self._decision,
            confidence=self._conf,
            risks=self._risks,
            next_actions=self._actions,
            raw=self._raw,
        )
