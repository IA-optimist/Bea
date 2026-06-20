"""
core/schemas/final_output.py — Kensho-style Result Envelope for mission output.

Every mission returns a deterministic FinalOutput, independent of agent composition.
Flutter always receives consistent schema. No ambiguous outputs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional, cast


@dataclass
class AgentError:
    """Structured error from an agent execution."""
    type: str = "unknown"
    message: str = ""
    recoverable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentOutput:
    """Output from a single agent within a mission."""
    agent_name: str
    status: Literal["SUCCESS", "ERROR", "SKIPPED"] = "SUCCESS"
    output_text: Optional[str] = None
    structured_data: Optional[dict[str, Any]] = None
    error: Optional[AgentError] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "agent_name": self.agent_name,
            "status": self.status,
            "output_text": self.output_text,
            "structured_data": self.structured_data,
        }
        if self.error:
            d["error"] = self.error.to_dict()
        return d


@dataclass
class DecisionStep:
    """A single step in the decision trace."""
    phase: str                  # e.g. "classify", "plan", "execute"
    description: str = ""
    result: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutputMetrics:
    """Execution metrics for the mission."""
    duration_seconds: Optional[float] = None
    token_usage: Optional[int] = None
    cost_estimate: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class FinalOutput:
    """
    Kensho-style Result Envelope.

    Deterministic, structured output for every mission.
    Flutter receives this schema regardless of agent composition.
    """
    mission_id: str
    trace_id: str = ""
    status: Literal["COMPLETED", "FAILED", "CANCELLED"] = "COMPLETED"
    summary: str = ""
    agent_outputs: list[AgentOutput] = field(default_factory=list)
    decision_trace: list[DecisionStep] = field(default_factory=list)
    metrics: OutputMetrics = field(default_factory=OutputMetrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "trace_id": self.trace_id,
            "status": self.status,
            "summary": self.summary,
            "agent_outputs": [a.to_dict() for a in self.agent_outputs],
            "decision_trace": [d.to_dict() for d in self.decision_trace],
            "metrics": self.metrics.to_dict(),
        }

    @staticmethod
    def from_mission(mission_id: str, mission_status: str, summary: str,
                     agent_outputs_raw: dict[str, Any] | list[Any], decision_trace_raw: dict[str, Any],
                     start_time: float = 0.0) -> "FinalOutput":
        """Build FinalOutput from existing mission data. Backward compatible."""
        # Map legacy status to canonical
        status_map = {
            "DONE": "COMPLETED", "REJECTED": "CANCELLED", "BLOCKED": "FAILED",
            "COMPLETED": "COMPLETED", "FAILED": "FAILED", "CANCELLED": "CANCELLED",
        }
        canonical_status = cast(
            Literal["COMPLETED", "FAILED", "CANCELLED"],
            status_map.get(str(mission_status).upper(), "COMPLETED"),
        )

        # Build agent outputs
        agent_list = []
        if isinstance(agent_outputs_raw, dict):
            for name, text in agent_outputs_raw.items():
                agent_list.append(AgentOutput(
                    agent_name=name,
                    status="SUCCESS" if text else "SKIPPED",
                    output_text=str(text)[:3000] if text else None,
                ))
        elif isinstance(agent_outputs_raw, list):
            for item in agent_outputs_raw:
                if isinstance(item, dict):
                    agent_list.append(AgentOutput(
                        agent_name=item.get("agent_name", "unknown"),
                        status=item.get("status", "SUCCESS"),
                        output_text=item.get("result") or item.get("output_text"),
                    ))

        # Build decision trace
        trace_steps = []
        if isinstance(decision_trace_raw, dict):
            for key, value in decision_trace_raw.items():
                if key in ("mission_type", "complexity", "risk_score",
                           "confidence_score", "selected_agents"):
                    trace_steps.append(DecisionStep(
                        phase=key,
                        result=str(value),
                    ))

        # Metrics
        duration = (time.time() - start_time) if start_time > 0 else None
        metrics = OutputMetrics(duration_seconds=duration)

        return FinalOutput(
            mission_id=mission_id,
            status=canonical_status,
            summary=summary[:500] if summary else "",
            agent_outputs=agent_list,
            decision_trace=trace_steps,
            metrics=metrics,
        )
