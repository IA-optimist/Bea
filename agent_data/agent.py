"""
agent_data/agent.py — DataAgent: read-only SQL with explain-before-execute.

Flow:
  1. Check SQL safety (SELECT only, no injection, LIMIT capped)
  2. Generate human-readable explanation of what the query does
  3. Present explanation to human (or caller) for approval
  4. Only after approval: execute via registered backend
  5. Return DataQueryReport with full audit trail

Wire a real DB backend via set_db_backend().
"""
from __future__ import annotations

from typing import Any, Callable, Awaitable
import time

import structlog

from agent_data.sql_policy import check_sql_safety, MAX_ROWS
from agent_data.reports import DataQueryReport

log = structlog.get_logger("bea.data.agent")

DBBackend = Callable[[str], Awaitable[list[dict[str, Any]]]]


class DataAgent:
    """
    Read-only data agent.

    INVARIANTS:
    - Only SELECT queries execute
    - explain() must be called before execute()
    - MAX_ROWS enforced at query level
    - Secrets never appear in output
    """

    def __init__(self) -> None:
        self._db: DBBackend | None = None

    def set_db_backend(self, fn: DBBackend) -> None:
        """Wire a real database backend (must return list of dicts)."""
        self._db = fn

    def explain(self, query: str) -> dict[str, Any]:
        """
        Validate query and produce a human-readable explanation.

        Returns dict with:
          - safe: bool
          - safe_query: str (with LIMIT injected)
          - explanation: str
          - reason: str | None (if blocked)
        """
        result = check_sql_safety(query)
        if not result.safe:
            return {
                "safe": False,
                "safe_query": None,
                "explanation": None,
                "reason": result.reason,
            }

        # Generate plain-English explanation
        sql = result.safe_query or ""
        lines = sql.upper().split()
        tables = self._extract_tables(sql)
        has_join = "JOIN" in lines
        has_where = "WHERE" in lines
        has_group = "GROUP" in lines
        limit_note = f"(max {MAX_ROWS} rows)"

        explanation_parts = [f"Reads data from: {', '.join(tables) or 'unknown table'} {limit_note}."]
        if has_join:
            explanation_parts.append("Joins multiple tables.")
        if has_where:
            explanation_parts.append("Filters rows by a WHERE condition.")
        if has_group:
            explanation_parts.append("Groups results by one or more columns.")

        return {
            "safe": True,
            "safe_query": result.safe_query,
            "explanation": " ".join(explanation_parts),
            "reason": None,
        }

    async def execute(
        self,
        query: str,
        *,
        approved_by: str,
        agent_id: str | None = None,
        mission_id: str | None = None,
    ) -> DataQueryReport:
        """
        Execute a pre-approved query.

        approved_by MUST be non-empty — callers must confirm human approval.
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("approved_by is required — data queries need human approval before execution")

        explanation_data = self.explain(query)
        if not explanation_data["safe"]:
            raise ValueError(f"query blocked by safety policy: {explanation_data['reason']}")

        safe_query = explanation_data["safe_query"]
        explanation = explanation_data["explanation"] or "Query approved for execution."

        log.info(
            "data_agent_execute",
            query_preview=query[:80],
            approved_by=approved_by,
            agent_id=agent_id,
        )

        if self._db is None:
            # No backend wired — return empty result (not an error in test mode)
            return DataQueryReport(
                original_query=query,
                safe_query=safe_query,
                explanation=explanation,
                schema=[],
                rows=[],
                row_count=0,
                truncated=False,
                agent_id=agent_id,
                mission_id=mission_id,
                approved_by=approved_by,
            )

        t0 = time.monotonic()
        rows = await self._db(safe_query)
        ms = int((time.monotonic() - t0) * 1000)
        schema = list(rows[0].keys()) if rows else []
        truncated = len(rows) >= MAX_ROWS
        return DataQueryReport(
            original_query=query,
            safe_query=safe_query,
            explanation=explanation,
            schema=schema,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution_ms=ms,
            agent_id=agent_id,
            mission_id=mission_id,
            approved_by=approved_by,
        )

    @staticmethod
    def _extract_tables(sql: str) -> list[str]:
        """Very simple heuristic to extract table names from SQL."""
        import re
        # Find words after FROM and JOIN
        tables = re.findall(
            r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
            sql, re.IGNORECASE
        )
        return list(dict.fromkeys(tables))[:5]  # deduplicate, cap at 5
