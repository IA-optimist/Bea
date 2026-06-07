"""
BEA MAX — Trace Intelligence
=================================
Enhanced trace analysis for production-grade observability.

Takes raw trace events (from core/trace.py MissionTrace) and produces:
  - Structured summaries: what happened, which model, which tools, timing, outcome
  - Failure root cause analysis
  - Timing breakdown (where time was spent)
  - Actionable trace digest for operators

Does NOT replace core/trace.py — extends it with analysis.

Usage:
    from core.trace_intelligence import TraceSummarizer
    summary = TraceSummarizer.summarize(mission_id)
    digest  = TraceSummarizer.digest(mission_id)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ToolCall:
    """Extracted tool call from trace."""
    tool: str
    success: bool
    duration_ms: float = 0
    error: str = ""
    timestamp: float = 0


@dataclass
class ModelCall:
    """Extracted model/LLM call from trace."""
    model_id: str
    role: str = ""
    duration_ms: float = 0
    tokens: int = 0
    success: bool = True
    timestamp: float = 0


@dataclass
class TimingBreakdown:
    """Where time was spent in a mission."""
    total_ms: float = 0
    planning_ms: float = 0
    execution_ms: float = 0
    tool_ms: float = 0
    model_ms: float = 0
    approval_wait_ms: float = 0
    other_ms: float = 0

    @property
    def breakdown_pct(self) -> dict[str, float]:
        if self.total_ms <= 0:
            return {}
        return {
            "planning": round(self.planning_ms / self.total_ms * 100, 1),
            "execution": round(self.execution_ms / self.total_ms * 100, 1),
            "tools": round(self.tool_ms / self.total_ms * 100, 1),
            "models": round(self.model_ms / self.total_ms * 100, 1),
            "approval_wait": round(self.approval_wait_ms / self.total_ms * 100, 1),
            "other": round(self.other_ms / self.total_ms * 100, 1),
        }


@dataclass
class FailureAnalysis:
    """Root cause analysis of a mission failure."""
    failed: bool = False
    primary_cause: str = ""       # timeout, tool_crash, model_error, validation, approval_timeout
    failed_component: str = ""    # which component failed
    error_message: str = ""
    error_chain: list[str] = field(default_factory=list)  # sequence of errors
    recoverable: bool = False
    recommendation: str = ""


@dataclass
class TraceSummary:
    """Complete trace analysis for a mission."""
    mission_id: str
    status: str = "unknown"       # success, failed, timeout, in_progress
    duration_ms: float = 0
    model_calls: list[ModelCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    timing: TimingBreakdown = field(default_factory=TimingBreakdown)
    failure: FailureAnalysis = field(default_factory=FailureAnalysis)
    event_count: int = 0
    components_involved: list[str] = field(default_factory=list)
    primary_model: str = ""
    primary_tool: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """Human-readable one-paragraph digest."""
        lines = [f"Mission {self.mission_id}: {self.status.upper()}"]
        if self.duration_ms > 0:
            lines.append(f"Duration: {self.duration_ms:.0f}ms")

        if self.primary_model:
            lines.append(f"Primary model: {self.primary_model}")
        if self.model_calls:
            lines.append(f"Model calls: {len(self.model_calls)}")

        if self.tool_calls:
            ok = sum(1 for t in self.tool_calls if t.success)
            fail = len(self.tool_calls) - ok
            lines.append(f"Tool calls: {len(self.tool_calls)} ({ok} ok, {fail} failed)")
            if self.primary_tool:
                lines.append(f"Primary tool: {self.primary_tool}")

        # Timing
        pct = self.timing.breakdown_pct
        if pct:
            parts = [f"{k}={v}%" for k, v in pct.items() if v > 0]
            if parts:
                lines.append(f"Time split: {', '.join(parts)}")

        # Failure
        if self.failure.failed:
            lines.append(f"FAILURE: {self.failure.primary_cause} in {self.failure.failed_component}")
            if self.failure.error_message:
                lines.append(f"  Error: {self.failure.error_message[:200]}")
            if self.failure.recommendation:
                lines.append(f"  Recommendation: {self.failure.recommendation}")

        return "\n".join(lines)


class TraceSummarizer:
    """Analyzes raw trace events and produces structured summaries."""

    @staticmethod
    def summarize_events(mission_id: str, events: list[dict]) -> TraceSummary:
        """Produce a TraceSummary from raw trace events."""
        summary = TraceSummary(mission_id=mission_id, event_count=len(events))

        if not events:
            summary.status = "no_trace"
            return summary

        # Extract components
        components = set()
        model_calls: list[ModelCall] = []
        tool_calls: list[ToolCall] = []
        errors: list[str] = []

        # Timing accumulators
        first_ts = events[0].get("ts", 0)
        last_ts = events[-1].get("ts", 0)
        planning_ms = 0.0
        execution_ms = 0.0
        tool_ms = 0.0
        model_ms = 0.0
        approval_ms = 0.0

        for e in events:
            comp = e.get("component", "unknown")
            components.add(comp)
            event_type = e.get("event", "")
            dur = e.get("duration_ms", 0)
            ts = e.get("ts", 0)

            # Model calls
            if "model" in event_type or "llm" in event_type or e.get("model_id"):
                mc = ModelCall(
                    model_id=e.get("model_id", e.get("model", "unknown")),
                    role=e.get("role", comp),
                    duration_ms=dur,
                    tokens=e.get("tokens", 0),
                    success=e.get("ok", True) is not False,
                    timestamp=ts,
                )
                model_calls.append(mc)
                model_ms += dur

            # Tool calls
            if "tool" in event_type or comp == "tool_executor" or e.get("tool"):
                tc = ToolCall(
                    tool=e.get("tool", e.get("tool_name", "unknown")),
                    success=e.get("ok", True) is not False,
                    duration_ms=dur,
                    error=e.get("error", ""),
                    timestamp=ts,
                )
                tool_calls.append(tc)
                tool_ms += dur

            # Planning
            if "plan" in event_type or comp == "planner":
                planning_ms += dur

            # Execution
            if "execut" in event_type or comp == "executor":
                execution_ms += dur

            # Approval wait
            if "approval" in event_type:
                approval_ms += dur

            # Errors
            if e.get("ok") is False or "error" in event_type or "fail" in event_type:
                err_msg = e.get("error", e.get("message", event_type))
                if err_msg:
                    errors.append(str(err_msg)[:200])

        # Timing
        total_ms = (last_ts - first_ts) * 1000 if last_ts > first_ts else 0
        other_ms = max(0, total_ms - planning_ms - execution_ms - tool_ms - model_ms - approval_ms)
        summary.timing = TimingBreakdown(
            total_ms=round(total_ms, 1), planning_ms=round(planning_ms, 1),
            execution_ms=round(execution_ms, 1), tool_ms=round(tool_ms, 1),
            model_ms=round(model_ms, 1), approval_wait_ms=round(approval_ms, 1),
            other_ms=round(other_ms, 1))
        summary.duration_ms = round(total_ms, 1)

        # Model + tool lists
        summary.model_calls = model_calls
        summary.tool_calls = tool_calls
        summary.components_involved = sorted(components)

        # Primary model (most used)
        if model_calls:
            model_counts: dict[str, int] = {}
            for mc in model_calls:
                model_counts[mc.model_id] = model_counts.get(mc.model_id, 0) + 1
            summary.primary_model = max(model_counts, key=model_counts.get)

        # Primary tool (most called)
        if tool_calls:
            tool_counts: dict[str, int] = {}
            for tc in tool_calls:
                tool_counts[tc.tool] = tool_counts.get(tc.tool, 0) + 1
            summary.primary_tool = max(tool_counts, key=tool_counts.get)

        # Status determination
        has_done = any(e.get("event") in ("mission_completed", "done", "success") for e in events)
        has_fail = any(e.get("event") in ("mission_failed", "failed", "error", "crash") for e in events)
        has_timeout = any("timeout" in str(e.get("event", "")).lower() for e in events)

        if has_timeout:
            summary.status = "timeout"
        elif has_fail and not has_done:
            summary.status = "failed"
        elif has_done:
            summary.status = "success"
        elif errors:
            summary.status = "failed"
        else:
            summary.status = "in_progress"

        # Failure analysis
        if summary.status in ("failed", "timeout"):
            fa = FailureAnalysis(failed=True)

            if has_timeout:
                fa.primary_cause = "timeout"
                fa.recommendation = "Increase timeout or reduce mission scope"
            elif any("tool" in e for e in errors):
                fa.primary_cause = "tool_crash"
                fa.recommendation = "Check tool health and retry config"
            elif any("model" in e or "llm" in e for e in errors):
                fa.primary_cause = "model_error"
                fa.recommendation = "Check model health and fallback config"
            elif any("approval" in e for e in errors):
                fa.primary_cause = "approval_timeout"
                fa.recommendation = "Lower risk threshold or pre-approve this mission type"
            elif any("valid" in e for e in errors):
                fa.primary_cause = "validation"
                fa.recommendation = "Fix input validation or relax constraints"
            else:
                fa.primary_cause = "unknown"
                fa.recommendation = "Review trace events for details"

            # Find failed component
            for e in reversed(events):
                if e.get("ok") is False or "error" in e.get("event", ""):
                    fa.failed_component = e.get("component", "unknown")
                    fa.error_message = str(e.get("error", e.get("message", "")))[:300]
                    break

            fa.error_chain = errors[-5:]  # Last 5 errors
            fa.recoverable = fa.primary_cause in ("timeout", "model_error", "tool_crash")
            summary.failure = fa

        return summary

    @staticmethod
    def summarize(mission_id: str, workspace_dir: str = "workspace") -> TraceSummary:
        """Load trace from disk and summarize."""
        from core.trace import MissionTrace
        trace = MissionTrace(mission_id, workspace_dir=workspace_dir)
        events = trace.get_events(limit=10000)
        return TraceSummarizer.summarize_events(mission_id, events)

    @staticmethod
    def digest(mission_id: str, workspace_dir: str = "workspace") -> str:
        """One-paragraph human-readable digest."""
        return TraceSummarizer.summarize(mission_id, workspace_dir).digest()
