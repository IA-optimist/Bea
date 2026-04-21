"""
JARVIS MAX — ImprovementMemory
Persists critic feedback and tracks agent improvement over time.

DISTINCTION (Cas B — deux fichiers coexistent intentionnellement) :
  Ce fichier (core/improvement_memory.py) :
    - Responsabilité : suivi des scores d'agents (score_before / score_after / feedback)
    - Backend : SQLite (primary) + asyncpg (upgrade path), ASYNC
    - Utilisé par : core/learning_loop.py, api/routes/learning.py, core/orchestrator_v2.py
    - Classe : ImprovementMemory / get_improvement_memory(settings)

  L'autre fichier (core/self_improvement/improvement_memory.py) :
    - Responsabilité : historique des tentatives du pipeline self-improve (candidate_type / outcome)
    - Backend : JSON file (workspace/self_improvement/history.json), SYNCHRONE
    - Utilisé par : core/self_improvement/safe_executor.py, api/routes/self_improvement.py
    - Classe : SelfImprovementMemory / get_improvement_memory() (sans settings)

  Ne pas fusionner — les deux servent des couches distinctes.

Storage: SQLite (primary, always available) with asyncpg upgrade path.

Table schema:
    improvements(
        id          TEXT PRIMARY KEY,
        agent_name  TEXT NOT NULL,
        task_hash   TEXT NOT NULL,
        task_snippet TEXT,
        score_before REAL,
        score_after  REAL,
        delta        REAL GENERATED ALWAYS AS (score_after - score_before) VIRTUAL,
        feedback     TEXT,
        timestamp    REAL
    )

Usage:
    mem = get_improvement_memory(settings)
    await mem.ensure_table()
    await mem.record_improvement("coder-agent", task, 4.5, 7.2, "Added error handling")
    stats = await mem.get_agent_stats("coder-agent")
    top   = await mem.get_top_feedback("coder-agent", limit=5)
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
import uuid

import structlog

log = structlog.get_logger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS improvements (
    id           TEXT PRIMARY KEY,
    agent_name   TEXT NOT NULL,
    task_hash    TEXT NOT NULL,
    task_snippet TEXT,
    score_before REAL DEFAULT 0,
    score_after  REAL DEFAULT 0,
    feedback     TEXT DEFAULT '',
    timestamp    REAL DEFAULT 0
);
"""
_CREATE_IDX = "CREATE INDEX IF NOT EXISTS imp_agent_idx ON improvements(agent_name);"


class ImprovementMemory:
    """
    Persist critic improvement records.
    SQLite is always tried first (no external service needed).
    asyncpg is used if database_url is set and SQLite is not preferred.
    """

    def __init__(self, settings=None):
        self.s             = settings
        self._sqlite_path: str | None  = None
        self._pg_pool                  = None
        self._backend: str | None      = None   # "sqlite" | "pg" | None

    # ── Bootstrap ─────────────────────────────────────────────

    async def ensure_table(self) -> str:
        """Initialise storage backend. Returns "sqlite" or "pg"."""
        if self._backend:
            return self._backend

        # Try asyncpg first if DSN is configured
        dsn = getattr(self.s, "database_url", None) or getattr(self.s, "pg_dsn", None)
        if dsn:
            try:
                await self._pg_ensure(dsn)
                self._backend = "pg"
                log.debug("improvement_memory_backend_pg")
                return self._backend
            except Exception as e:
                log.debug("improvement_memory_pg_unavailable", err=str(e)[:80])

        # SQLite fallback (always available)
        await self._sqlite_ensure()
        self._backend = "sqlite"
        log.debug("improvement_memory_backend_sqlite", path=self._sqlite_path)
        return self._backend

    # ── Write ─────────────────────────────────────────────────

    async def record_improvement(
        self,
        agent_name:   str,
        task:         str,
        score_before: float,
        score_after:  float,
        feedback:     str = "",
    ) -> str:
        """Insert one improvement record. Returns the new row id."""
        if not self._backend:
            await self.ensure_table()

        row_id      = str(uuid.uuid4())
        task_hash   = hashlib.sha256(task.encode()).hexdigest()[:16]
        task_snippet = task[:200]
        ts           = time.time()

        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO improvements
                            (id, agent_name, task_hash, task_snippet,
                             score_before, score_after, feedback, timestamp)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8);
                        """,
                        row_id, agent_name, task_hash, task_snippet,
                        score_before, score_after, feedback, ts,
                    )
                return row_id
            except Exception as e:
                log.warning("improvement_memory_pg_write_failed", err=str(e)[:80])

        # SQLite
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._sqlite_insert,
            row_id, agent_name, task_hash, task_snippet,
            score_before, score_after, feedback, ts,
        )
        return row_id

    # ── Read ──────────────────────────────────────────────────

    async def get_agent_stats(self, agent_name: str) -> dict:
        """
        Returns aggregated stats for an agent.
        {avg_score_before, avg_score_after, total_tasks, improvement_rate, avg_delta}
        """
        if not self._backend:
            await self.ensure_table()

        rows = await self._fetch_all(agent_name)
        if not rows:
            return {
                "agent_name":       agent_name,
                "total_tasks":      0,
                "avg_score_before": 0.0,
                "avg_score_after":  0.0,
                "avg_delta":        0.0,
                "improvement_rate": 0.0,
            }

        befores = [r["score_before"] for r in rows]
        afters  = [r["score_after"]  for r in rows]
        deltas  = [a - b for a, b in zip(afters, befores)]
        improved = sum(1 for d in deltas if d > 0)

        return {
            "agent_name":       agent_name,
            "total_tasks":      len(rows),
            "avg_score_before": round(sum(befores) / len(befores), 2),
            "avg_score_after":  round(sum(afters)  / len(afters),  2),
            "avg_delta":        round(sum(deltas)  / len(deltas),  2),
            "improvement_rate": round(improved / len(rows),        2),
        }

    async def get_top_feedback(
        self, agent_name: str, limit: int = 5
    ) -> list[dict]:
        """
        Returns the feedback entries with highest score improvement (score_after - score_before).
        """
        if not self._backend:
            await self.ensure_table()

        rows = await self._fetch_all(agent_name)
        rows.sort(key=lambda r: r["score_after"] - r["score_before"], reverse=True)
        return rows[:limit]

    async def recent(self, agent_name: str, limit: int = 20) -> list[dict]:
        """Returns most recent records for agent, newest first."""
        if not self._backend:
            await self.ensure_table()
        rows = await self._fetch_all(agent_name)
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return rows[:limit]

    async def list_agents(self) -> list[str]:
        """Returns all distinct agent_names that have improvement records."""
        if not self._backend:
            await self.ensure_table()
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT DISTINCT agent_name FROM improvements ORDER BY agent_name;"
                    )
                return [r["agent_name"] for r in rows]
            except Exception as e:
                log.warning("improvement_memory_pg_list_agents_failed", err=str(e)[:80])
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sqlite_list_agents)

    def _sqlite_list_agents(self) -> list[str]:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        cur = con.execute(
            "SELECT DISTINCT agent_name FROM improvements ORDER BY agent_name;"
        )
        names = [r[0] for r in cur.fetchall()]
        con.close()
        return names

    # ── asyncpg helpers ───────────────────────────────────────

    async def _pg_ensure(self, dsn: str) -> None:
        import asyncpg
        self._pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        async with self._pg_pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
            await conn.execute(_CREATE_IDX)

    async def _get_pg_pool(self):
        if self._pg_pool is None:
            dsn = getattr(self.s, "database_url", None) or getattr(self.s, "pg_dsn", None)
            if not dsn:
                raise RuntimeError("No database_url configured")
            import asyncpg
            self._pg_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        return self._pg_pool

    async def _fetch_all(self, agent_name: str) -> list[dict]:
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM improvements WHERE agent_name=$1 "
                        "ORDER BY timestamp DESC;",
                        agent_name,
                    )
                return [dict(r) for r in rows]
            except Exception as e:
                log.warning("improvement_memory_pg_fetch_failed", err=str(e)[:80])
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sqlite_fetch_all, agent_name)

    # ── SQLite helpers ────────────────────────────────────────

    async def _sqlite_ensure(self) -> None:
        if not self._sqlite_path:
            try:
                from core.db import get_sqlite_path
                self._sqlite_path = get_sqlite_path()
            except Exception:
                self._sqlite_path = os.path.join(
                    tempfile.gettempdir(), "jarvis_improvements.db"
                )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sqlite_create_table)

    def _sqlite_create_table(self) -> None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.execute(_CREATE_TABLE)
        con.execute(_CREATE_IDX)
        con.commit()
        con.close()

    def _sqlite_insert(
        self, row_id, agent_name, task_hash, task_snippet,
        score_before, score_after, feedback, ts
    ) -> None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.execute(
            "INSERT OR IGNORE INTO improvements "
            "(id, agent_name, task_hash, task_snippet, "
            " score_before, score_after, feedback, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?);",
            (row_id, agent_name, task_hash, task_snippet,
             score_before, score_after, feedback, ts),
        )
        con.commit()
        con.close()

    def _sqlite_fetch_all(self, agent_name: str) -> list[dict]:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.row_factory = sqlite3.Row
        cur = con.execute(
            "SELECT * FROM improvements WHERE agent_name=? ORDER BY timestamp DESC;",
            (agent_name,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        con.close()
        return rows


# ── Singleton ─────────────────────────────────────────────────

_mem: ImprovementMemory | None = None


def get_improvement_memory(settings=None) -> ImprovementMemory:
    global _mem
    if _mem is None:
        _mem = ImprovementMemory(settings)
    return _mem
