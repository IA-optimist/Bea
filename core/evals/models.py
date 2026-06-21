"""Data models for bea eval results."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class EvalResult:
    """Result of a single bea eval task."""

    eval_name: str
    success: bool
    score: float  # 0.0–1.0
    duration_ms: int
    files_used: list[str] = field(default_factory=list)
    memories_retrieved: list[str] = field(default_factory=list)
    model_class_selected: str | None = None
    error: str | None = None
    cost_estimate: float | None = None
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    """Aggregate report returned by a bea eval run."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    created_at: float = field(default_factory=time.time)
    results: list[EvalResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
        }

    def overall_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)
