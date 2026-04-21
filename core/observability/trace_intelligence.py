"""
core/observability/trace_intelligence.py — AI OS Trace Intelligence.

Analyzes traces for self-improvement, performance evaluation,
error pattern detection, and capability reliability scoring.
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("jarvis.trace_intel")

TRACE_DIR = Path("workspace/traces")


@dataclass
class TraceSegment:
    """Structured trace segment for analysis."""
    phase: str
    action: str
    result: str = ""
    duration_ms: int = 0
    error: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class TraceAnalysis:
    """Analysis result for a single trace."""
    mission_id: str
    total_events: int = 0
    phases_completed: int = 0
    phases_failed: int = 0
    total_duration_ms: int = 0
    error_types: list[str] = field(default_factory=list)
    capabilities_used: list[str] = field(default_factory=list)
    agents_involved: list[str] = field(default_factory=list)
    outcome: str = "unknown"
    
    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "total_events": self.total_events,
            "phases_completed": self.phases_completed,
            "phases_failed": self.phases_failed,
            "total_duration_ms": self.total_duration_ms,
            "error_types": self.error_types,
            "capabilities_used": self.capabilities_used,
            "agents_involved": self.agents_involved,
            "outcome": self.outcome,
        }


def load_trace(mission_id: str) -> list[TraceSegment]:
    """Load trace from JSONL file."""
    path = TRACE_DIR / f"{mission_id}.jsonl"
    if not path.exists():
        return []
    segments = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            segments.append(TraceSegment(
                phase=d.get("phase", ""),
                action=d.get("action", ""),
                result=d.get("data", {}).get("result", ""),
                duration_ms=d.get("data", {}).get("duration_ms", 0),
                error=d.get("reason", ""),
                data=d.get("data", {}),
            ))
        except Exception:
            continue
    return segments


def analyze_trace(mission_id: str) -> TraceAnalysis:
    """Analyze a mission trace for intelligence."""
    segments = load_trace(mission_id)
    analysis = TraceAnalysis(mission_id=mission_id, total_events=len(segments))
    
    for seg in segments:
        if seg.phase == "execute":
            analysis.agents_involved.append(seg.action)
            if "EXECUTED" in str(seg.result):
                analysis.phases_completed += 1
            elif "FAILED" in str(seg.result):
                analysis.phases_failed += 1
        elif seg.phase == "classify":
            analysis.capabilities_used.append(seg.action)
        elif seg.phase == "complete":
            analysis.outcome = seg.action  # "DONE" or "FAILED"
        
        if seg.duration_ms:
            analysis.total_duration_ms += seg.duration_ms
        if seg.error:
            analysis.error_types.append(seg.error)
    
    return analysis


def error_patterns(limit: int = 50) -> dict:
    """Detect error patterns across recent traces."""
    if not TRACE_DIR.exists():
        return {"patterns": [], "total_traces": 0}
    
    error_counts: dict[str, int] = {}
    total = 0
    
    for f in sorted(TRACE_DIR.glob("*.jsonl"))[-limit:]:
        total += 1
        mid = f.stem
        analysis = analyze_trace(mid)
        for err in analysis.error_types:
            error_counts[err] = error_counts.get(err, 0) + 1
    
    patterns = sorted(error_counts.items(), key=lambda x: -x[1])
    return {
        "total_traces": total,
        "error_patterns": [{"error": e, "count": c, "rate": round(c/total, 2)} for e, c in patterns[:10]],
    }


def capability_reliability() -> dict:
    """Score capability reliability from traces."""
    if not TRACE_DIR.exists():
        return {}
    
    cap_stats: dict[str, dict] = {}
    
    for f in sorted(TRACE_DIR.glob("*.jsonl"))[-100:]:
        analysis = analyze_trace(f.stem)
        for cap in analysis.capabilities_used:
            if cap not in cap_stats:
                cap_stats[cap] = {"total": 0, "success": 0}
            cap_stats[cap]["total"] += 1
            if analysis.outcome == "DONE":
                cap_stats[cap]["success"] += 1
    
    return {
        cap: {
            "total": s["total"],
            "success": s["success"],
            "reliability": round(s["success"] / s["total"], 2) if s["total"] > 0 else 0,
        }
        for cap, s in cap_stats.items()
    }
