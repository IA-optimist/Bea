"""
agent_data — Data Agent (Vanna/Wren pattern): read-only SQL with explain-before-execute.

Key constraints:
  - SELECT only — any DML/DDL is rejected before execution
  - MAX_ROWS = 1000 per query
  - SQL must be explained to human BEFORE execution
  - No secrets, no PII in output
  - Queries are logged for audit

Public surface:
    from agent_data import check_sql_safety, DataAgent, DataQueryReport
"""
from __future__ import annotations

from agent_data.sql_policy import check_sql_safety, SQLSafetyResult, MAX_ROWS
from agent_data.agent import DataAgent
from agent_data.reports import DataQueryReport

__all__ = [
    "check_sql_safety",
    "SQLSafetyResult",
    "MAX_ROWS",
    "DataAgent",
    "DataQueryReport",
]
