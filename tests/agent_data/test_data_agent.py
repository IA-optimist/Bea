"""
tests/agent_data/test_data_agent.py — Data Agent and SQL policy tests.
"""
from __future__ import annotations

import pytest

from agent_data.sql_policy import check_sql_safety, MAX_ROWS, SQLSafetyResult
from agent_data.agent import DataAgent
from agent_data.reports import DataQueryReport


# ── SQL policy tests ──────────────────────────────────────────────────────────

class TestSQLPolicy:
    def test_select_allowed(self):
        r = check_sql_safety("SELECT id, name FROM users")
        assert r.safe
        assert r.safe_query is not None
        assert "LIMIT" in (r.safe_query or "")

    def test_limit_injected_when_missing(self):
        r = check_sql_safety("SELECT * FROM events")
        assert r.safe
        assert f"LIMIT {MAX_ROWS}" in (r.safe_query or "")

    def test_limit_capped(self):
        r = check_sql_safety(f"SELECT * FROM logs LIMIT {MAX_ROWS + 9999}")
        assert r.safe
        assert f"LIMIT {MAX_ROWS}" in (r.safe_query or "")

    def test_limit_preserved_when_small(self):
        r = check_sql_safety("SELECT * FROM logs LIMIT 10")
        assert r.safe
        assert "LIMIT 10" in (r.safe_query or "")

    def test_insert_blocked(self):
        r = check_sql_safety("INSERT INTO users VALUES (1, 'x')")
        assert not r.safe
        assert "SELECT" in (r.reason or "").upper()

    def test_update_blocked(self):
        r = check_sql_safety("UPDATE users SET name='x' WHERE id=1")
        assert not r.safe

    def test_delete_blocked(self):
        r = check_sql_safety("DELETE FROM users WHERE id=1")
        assert not r.safe

    def test_drop_blocked(self):
        r = check_sql_safety("DROP TABLE users")
        assert not r.safe

    def test_truncate_blocked(self):
        r = check_sql_safety("TRUNCATE TABLE sessions")
        assert not r.safe

    def test_stacked_statements_blocked(self):
        r = check_sql_safety("SELECT 1; DROP TABLE users")
        assert not r.safe

    def test_inline_comment_blocked(self):
        r = check_sql_safety("SELECT * FROM users -- ignore where clause")
        assert not r.safe

    def test_block_comment_blocked(self):
        r = check_sql_safety("SELECT /* admin */ * FROM users")
        assert not r.safe

    def test_non_select_start_blocked(self):
        r = check_sql_safety("EXPLAIN SELECT * FROM users")
        assert not r.safe

    def test_select_into_blocked(self):
        r = check_sql_safety("SELECT * INTO backup FROM users")
        assert not r.safe


# ── DataAgent tests ───────────────────────────────────────────────────────────

class TestDataAgent:
    def setup_method(self):
        self.agent = DataAgent()

    def test_explain_safe_query(self):
        info = self.agent.explain("SELECT id FROM missions")
        assert info["safe"] is True
        assert info["explanation"] is not None
        assert "missions" in info["explanation"].lower()

    def test_explain_unsafe_query(self):
        info = self.agent.explain("DROP TABLE missions")
        assert info["safe"] is False
        assert info["reason"] is not None

    def test_explain_includes_limit(self):
        info = self.agent.explain("SELECT * FROM logs")
        assert "safe_query" in info
        assert "LIMIT" in (info["safe_query"] or "")

    @pytest.mark.asyncio
    async def test_execute_requires_approved_by(self):
        with pytest.raises(ValueError, match="approved_by"):
            await self.agent.execute("SELECT 1", approved_by="")

    @pytest.mark.asyncio
    async def test_execute_blocks_unsafe(self):
        with pytest.raises(ValueError, match="blocked"):
            await self.agent.execute(
                "DELETE FROM users",
                approved_by="human-max",
            )

    @pytest.mark.asyncio
    async def test_execute_no_backend_returns_empty(self):
        # No backend wired — should return empty result
        report = await self.agent.execute(
            "SELECT id FROM users",
            approved_by="human-max",
            agent_id="analyst-1",
        )
        assert isinstance(report, DataQueryReport)
        assert report.row_count == 0
        assert report.approved_by == "human-max"

    @pytest.mark.asyncio
    async def test_execute_with_mock_backend(self):
        async def mock_db(query: str) -> list[dict]:
            return [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
        self.agent.set_db_backend(mock_db)
        report = await self.agent.execute(
            "SELECT id, name FROM users",
            approved_by="human-max",
        )
        assert report.row_count == 2
        assert "id" in report.schema
        assert not report.truncated

    @pytest.mark.asyncio
    async def test_execute_truncation_flagged(self):
        async def big_db(query: str) -> list[dict]:
            return [{"id": i} for i in range(MAX_ROWS)]
        self.agent.set_db_backend(big_db)
        report = await self.agent.execute(
            "SELECT id FROM big_table",
            approved_by="human-max",
        )
        assert report.truncated  # hit MAX_ROWS

    def test_report_summary_contains_explanation(self):
        report = DataQueryReport(
            original_query="SELECT id FROM missions",
            safe_query=f"SELECT id FROM missions LIMIT {MAX_ROWS}",
            explanation="Reads data from missions table (max 1000 rows).",
            schema=["id"],
            rows=[{"id": 1}],
            row_count=1,
            approved_by="human",
        )
        summary = report.to_summary()
        assert "missions" in summary.lower()
        assert "Rows: 1" in summary
