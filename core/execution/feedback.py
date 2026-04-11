"""
core/execution/feedback.py — Execution feedback signals.

Captures structured signals from artifact builds and feeds them into
strategic memory, capability performance, and self-model.

Design:
  - BuildConfidence: composite quality estimate for a build
  - ExecutionTrace: full traceability record for a build
  - FeedbackCollector: routes signals to memory systems
  - All fail-open: feedback failures never crash builds
"""
from __future__ import annotations

import time
import uuid
import structlog
from dataclasses import dataclass, field
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger("execution.feedback")


@dataclass
class BuildConfidence:
    """
    Composite confidence score for a build result.

    Factors:
      - validation_score: fraction of checks passed
      - content_score: quality of generated content (0-1)
      - tool_score: tool reliability during build (0-1)
      - iteration_count: how many attempts were needed (lower=better)
    """
    validation_score: float = 0.0
    content_score: float = 0.0
    tool_score: float = 1.0
    iteration_count: int = 1

    @property
    def composite(self) -> float:
        """
        Weighted composite confidence (0.0-1.0).
        validation=40%, content=30%, tool=20%, iteration_penalty=10%.
        """
        iter_penalty = max(0.0, 1.0 - (self.iteration_count - 1) * 0.2)
        raw = (
            self.validation_score * 0.4
            + self.content_score * 0.3
            + self.tool_score * 0.2
            + iter_penalty * 0.1
        )
        return round(max(0.0, min(1.0, raw)), 3)

    def to_dict(self) -> dict:
        return {
            "validation_score": round(self.validation_score, 3),
            "content_score": round(self.content_score, 3),
            "tool_score": round(self.tool_score, 3),
            "iteration_count": self.iteration_count,
            "composite": self.composite,
        }


@dataclass
class ExecutionTrace:
    """
    Full traceability record for an artifact build.

    Links: mission → plan → graph → artifact → build → outcome.
    """
    trace_id: str = ""
    artifact_id: str = ""
    artifact_type: str = ""
    source_capability: str = ""
    source_schema: str = ""
    source_mission_id: str = ""
    graph_id: str = ""

    # Build details
    build_success: bool = False
    build_duration_ms: float = 0
    tools_invoked: list[str] = field(default_factory=list)
    files_produced: list[str] = field(default_factory=list)
    validation_passed: list[str] = field(default_factory=list)
    validation_failed: list[str] = field(default_factory=list)

    # Confidence
    confidence: BuildConfidence = field(default_factory=BuildConfidence)

    # Cost estimate
    estimated_cost_usd: float = 0.0  # LLM cost estimate

    # Policy
    policy_classification: str = "low"  # low, medium, high, critical
    policy_violations: list[str] = field(default_factory=list)

    # Timing
    created_at: float = field(default_factory=time.time)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = f"et-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "source_capability": self.source_capability,
            "source_schema": self.source_schema,
            "source_mission_id": self.source_mission_id,
            "graph_id": self.graph_id,
            "build_success": self.build_success,
            "build_duration_ms": round(self.build_duration_ms),
            "tools_invoked": self.tools_invoked,
            "files_produced": self.files_produced[-20:],
            "validation_passed": self.validation_passed,
            "validation_failed": self.validation_failed,
            "confidence": self.confidence.to_dict(),
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "policy_classification": self.policy_classification,
            "policy_violations": self.policy_violations,
            "created_at": self.created_at,
        }


def compute_confidence(
    validation_passed: list[str],
    validation_failed: list[str],
    content_quality: float = 0.5,
    tools_succeeded: int = 1,
    tools_failed: int = 0,
    iteration_count: int = 1,
) -> BuildConfidence:
    """Compute BuildConfidence from build outcome signals."""
    total_checks = len(validation_passed) + len(validation_failed)
    validation_score = len(validation_passed) / total_checks if total_checks > 0 else 0.0

    total_tools = tools_succeeded + tools_failed
    tool_score = tools_succeeded / total_tools if total_tools > 0 else 1.0

    return BuildConfidence(
        validation_score=validation_score,
        content_score=content_quality,
        tool_score=tool_score,
        iteration_count=iteration_count,
    )


def build_execution_trace(
    artifact,
    build_result,
    graph_id: str = "",
    estimated_cost: float = 0.0,
    policy_class: str = "low",
    policy_violations: list[str] | None = None,
) -> ExecutionTrace:
    """Build an ExecutionTrace from an artifact and build result."""
    confidence = compute_confidence(
        validation_passed=build_result.validation_passed,
        validation_failed=build_result.validation_failed,
        content_quality=0.7 if build_result.success else 0.1,
        tools_succeeded=len(build_result.tools_invoked),
        tools_failed=0 if build_result.success else 1,
    )
    return ExecutionTrace(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type.value if hasattr(artifact.artifact_type, 'value') else str(artifact.artifact_type),
        source_capability=artifact.source_capability,
        source_schema=artifact.source_schema,
        source_mission_id=artifact.source_mission_id,
        graph_id=graph_id,
        build_success=build_result.success,
        build_duration_ms=build_result.duration_ms,
        tools_invoked=build_result.tools_invoked,
        files_produced=build_result.output_files,
        validation_passed=build_result.validation_passed,
        validation_failed=build_result.validation_failed,
        confidence=confidence,
        estimated_cost_usd=estimated_cost,
        policy_classification=policy_class,
        policy_violations=policy_violations or [],
    )


class FeedbackCollector:
    """
    Routes execution feedback to downstream memory systems.

    Feeds:
      1. Strategic memory — outcome records
      2. Kernel performance — capability signals
      3. Self-model — limitation updates
    All fail-open.
    """

    def record(self, trace: ExecutionTrace) -> None:
        """Record execution trace to all downstream systems."""
        self._to_strategic_memory(trace)
        self._to_kernel_performance(trace)
        self._to_cognitive_journal(trace)

    def _to_strategic_memory(self, trace: ExecutionTrace) -> None:
        try:
            from core.economic.strategic_memory import get_strategic_memory, StrategicRecord
            get_strategic_memory().record(StrategicRecord(
                strategy_type=f"build.{trace.artifact_type}",
                playbook_id="",
                run_id=trace.artifact_id,
                context_features={"artifact_type": trace.artifact_type},
                schema_type=trace.source_schema,
                outcome_score=trace.confidence.composite,
                confidence=trace.confidence.composite,
                completeness=trace.confidence.validation_score,
                goal=trace.artifact_id,
                key_findings=[f"files={len(trace.files_produced)}"] if trace.build_success else [],
                failure_reasons=trace.validation_failed[:5],
            ))
        except Exception:
            _silent_log.debug("suppressed_exception", src='feedback.py')

    def _to_kernel_performance(self, trace: ExecutionTrace) -> None:
        try:
            from kernel.performance.tracker import get_performance_tracker
            tracker = get_performance_tracker()
            tracker.record_outcome(
                provider_id=f"build.{trace.artifact_type}",
                capability_id=trace.source_capability or "execution",
                success=trace.build_success,
                duration_ms=trace.build_duration_ms,
                quality=trace.confidence.composite,
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='feedback.py')

    def _to_cognitive_journal(self, trace: ExecutionTrace) -> None:
        try:
            from core.cognitive_events.emitter import emit
            from core.cognitive_events.types import EventType, EventSeverity
            sev = EventSeverity.INFO if trace.build_success else EventSeverity.WARNING
            emit(
                EventType.SYSTEM_EVENT,
                summary=f"Build {'OK' if trace.build_success else 'FAILED'}: {trace.artifact_type}",
                source="build_pipeline",
                mission_id=trace.source_mission_id,
                severity=sev,
                payload={
                    "trace_id": trace.trace_id,
                    "artifact_id": trace.artifact_id,
                    "confidence": trace.confidence.composite,
                    "files": len(trace.files_produced),
                    "policy": trace.policy_classification,
                },
                tags=["build", trace.artifact_type],
            )
        except Exception:
            _silent_log.debug("suppressed_exception", src='feedback.py')


# Singleton
_collector: FeedbackCollector | None = None

def get_feedback_collector() -> FeedbackCollector:
    global _collector
    if _collector is None:
        _collector = FeedbackCollector()
    return _collector
