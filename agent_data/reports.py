"""
agent_data/reports.py — DataQueryReport: structured result of a data query.

Every query result includes:
  - The original query (for audit)
  - The safe_query that was actually executed
  - A human-readable explanation (required)
  - Row count and schema
  - Whether the result was truncated (row_count hit MAX_ROWS)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DataQueryReport(BaseModel):
    """Structured, auditable result of a data agent query."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    original_query: str
    safe_query: str
    explanation: str = Field(min_length=20)  # human-readable explanation required
    schema: list[str] = Field(default_factory=list)  # column names
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False          # True if row_count == MAX_ROWS
    execution_ms: int = 0
    agent_id: str | None = None
    mission_id: str | None = None
    approved_by: str | None = None   # human approval reference
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def to_summary(self) -> str:
        trunc = " [TRUNCATED]" if self.truncated else ""
        return (
            f"Query: {self.original_query[:80]}\n"
            f"Rows: {self.row_count}{trunc}\n"
            f"Columns: {', '.join(self.schema)}\n"
            f"Explanation: {self.explanation}"
        )
