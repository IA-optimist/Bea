"""Episodic memory — SQLite store for completed missions."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path("workspace/memory/bea_episodes.db")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS bea_episodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id  TEXT    NOT NULL,
    goal        TEXT    NOT NULL,
    agents      TEXT    NOT NULL DEFAULT '[]',
    outcome     TEXT    NOT NULL DEFAULT '',
    success     INTEGER NOT NULL DEFAULT 0,
    domain      TEXT    NOT NULL DEFAULT 'general',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep_domain ON bea_episodes (domain);
CREATE INDEX IF NOT EXISTS idx_ep_ts     ON bea_episodes (ts DESC);
"""


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.executescript(_CREATE_SQL)
    return c


def store_episode(
    mission_id: str,
    goal: str,
    agents: list[str],
    outcome_summary: str,
    success: bool,
    domain: str = "general",
    duration_ms: int = 0,
) -> None:
    with _conn() as c:
        c.execute(
            """
            INSERT INTO bea_episodes
              (mission_id, goal, agents, outcome, success, domain, duration_ms, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                goal[:500],
                json.dumps(agents),
                outcome_summary[:800],
                int(success),
                domain,
                duration_ms,
                time.time(),
            ),
        )


def recall_similar(goal: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Keyword-overlap recall — no embedding required."""
    keywords = {w.lower() for w in goal.split() if len(w) > 3}
    if not keywords:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT mission_id, goal, agents, outcome, success, domain, duration_ms, ts "
            "FROM bea_episodes ORDER BY ts DESC LIMIT 200"
        ).fetchall()

    scored: list[tuple[int, dict]] = []
    for row in rows:
        ep_words = {w.lower() for w in row[1].split() if len(w) > 3}
        overlap = len(keywords & ep_words)
        if overlap > 0:
            scored.append((overlap, {
                "mission_id": row[0],
                "goal": row[1],
                "agents": json.loads(row[2]),
                "outcome": row[3],
                "success": bool(row[4]),
                "domain": row[5],
                "duration_ms": row[6],
                "ts": row[7],
                "_score": overlap,
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ep for _, ep in scored[:top_k]]


def recent_episodes(limit: int = 100, domain: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE domain = ?" if domain else ""
    params: tuple = (domain,) if domain else ()
    with _conn() as c:
        rows = c.execute(
            f"SELECT mission_id, goal, agents, outcome, success, domain, duration_ms, ts "
            f"FROM bea_episodes {where} ORDER BY ts DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [
        {
            "mission_id": r[0], "goal": r[1], "agents": json.loads(r[2]),
            "outcome": r[3], "success": bool(r[4]), "domain": r[5],
            "duration_ms": r[6], "ts": r[7],
        }
        for r in rows
    ]
