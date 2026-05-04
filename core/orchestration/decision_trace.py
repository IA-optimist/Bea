"""
core/orchestration/decision_trace.py — Structured trace of all orchestrator decisions.

Every major decision in a mission lifecycle is recorded here.
Enables full explainability: why this plan, why this tool, why retry.
"""
from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger("orchestration.trace")

_TRACE_DIR = Path("workspace/traces")


@dataclass
class TraceEntry:
    phase: str              # classify, plan, retrieve, execute, recover, store
    action: str             # what happened
    reason: str             # why
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class DecisionTrace:
    """Complete trace of decisions for one mission."""
    mission_id: str
    entries: list[TraceEntry] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def record(self, phase: str, action: str, reason: str = "", **data) -> None:
        entry = TraceEntry(phase=phase, action=action, reason=reason, data=data)
        self.entries.append(entry)
        log.debug("decision_trace",
                  mission_id=self.mission_id, phase=phase,
                  action=action, reason=reason[:60])

    # ── Cost tracking ────────────────────────────────
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0

    def record_cost(self, tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0) -> None:
        """Accumulate cost from an execution step."""
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd

    def cost_summary(self) -> dict:
        return {
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "phases": len(self.entries),
            "duration_s": round(time.time() - self.started_at, 2),
        }

    def human_summary(self) -> str:
        """Human-readable trace summary. For trust/explainability."""
        lines = [f"Mission {self.mission_id}:"]
        for e in self.entries:
            phase = e.phase.upper()
            action = e.action
            reason = e.reason
            if reason:
                lines.append(f"  {phase}: {action} — {reason}")
            else:
                lines.append(f"  {phase}: {action}")
        if self.total_cost_usd > 0:
            lines.append(f"  COST: ${self.total_cost_usd:.4f} ({self.total_tokens_in + self.total_tokens_out} tokens)")
        duration = round(self.entries[-1].ts - self.started_at, 1) if self.entries else 0
        lines.append(f"  DURATION: {duration}s across {len(self.entries)} steps")
        return "\n".join(lines)

    def summary(self) -> list[dict]:
        return [
            {"phase": e.phase, "action": e.action, "reason": e.reason,
             "ts": e.ts, **e.data}
            for e in self.entries
        ]

    def save(self) -> None:
        """Persist trace to workspace/traces/ as JSONL."""
        try:
            _TRACE_DIR.mkdir(parents=True, exist_ok=True)
            path = _TRACE_DIR / f"{self.mission_id}.jsonl"
            with open(path, "w") as f:
                for entry in self.entries:
                    f.write(json.dumps({
                        "phase": entry.phase,
                        "action": entry.action,
                        "reason": entry.reason,
                        "data": entry.data,
                        "ts": entry.ts,
                    }, ensure_ascii=False) + "\n")
        except Exception as e:
            log.debug("trace_save_failed", err=str(e)[:60])

    @staticmethod
    def load(mission_id: str) -> list[dict]:
        """Load a saved trace."""
        path = _TRACE_DIR / f"{mission_id}.jsonl"
        if not path.exists():
            return []
        entries = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries
