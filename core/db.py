"""
JARVIS MAX — SQLite Central Database
Singleton SQLite avec 4 tables : vault_entries, actions, missions, goals
Chemin : workspace/jarvismax.db
Utilise sqlite3 stdlib (zéro dépendance externe)
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_DB_PATH = Path("workspace/jarvismax.db")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_connection() -> sqlite3.Connection:
    """Retourne la connexion SQLite (singleton thread-safe).

    NOTE: This is the DEV/FALLBACK database. In production, modules should
    use PostgreSQL via settings.database_url. SQLite is used when:
    - DATABASE_URL is not set
    - asyncpg connection fails
    """
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
                try:
                    import os
                    if os.environ.get("PRODUCTION_MODE", "").lower() in ("1", "true", "yes"):
                        import logging
                        logging.getLogger("jarvis.db").warning(
                            "SQLite fallback active in PRODUCTION_MODE. "
                            "Set DATABASE_URL for PostgreSQL."
                        )
                    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    _init_schema(conn)
                    _conn = conn
                except Exception as exc:
                    # fail-open : retourne None, les modules feront fallback JSON
                    raise exc
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Crée les tables si elles n'existent pas."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS vault_entries (
        id TEXT PRIMARY KEY,
        type TEXT,
        content TEXT,
        source TEXT,
        confidence REAL,
        usage_count INTEGER DEFAULT 0,
        last_used TEXT,
        tags TEXT,
        related_to TEXT,
        valid INTEGER DEFAULT 1,
        created_at REAL,
        expires_at REAL
    );

    CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY,
        description TEXT,
        risk TEXT,
        target TEXT,
        impact TEXT,
        diff TEXT,
        rollback TEXT,
        mission_id TEXT,
        status TEXT DEFAULT 'PENDING',
        created_at REAL,
        approved_at REAL,
        rejected_at REAL,
        executed_at REAL,
        result TEXT DEFAULT '',
        note TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS missions (
        id TEXT PRIMARY KEY,
        user_input TEXT,
        intent TEXT,
        status TEXT,
        plan_summary TEXT,
        plan_steps TEXT,
        advisory_score REAL DEFAULT 0,
        advisory_decision TEXT DEFAULT 'UNKNOWN',
        advisory_issues TEXT,
        advisory_risks TEXT,
        action_ids TEXT,
        requires_validation INTEGER DEFAULT 1,
        auto_approved INTEGER DEFAULT 0,
        created_at REAL,
        updated_at REAL,
        completed_at REAL,
        note TEXT DEFAULT '',
        final_output TEXT DEFAULT '',
        summary TEXT DEFAULT '',
        agents_selected TEXT DEFAULT '[]',
        domain TEXT DEFAULT 'general',
        execution_trace TEXT DEFAULT '[]',
        decision_trace TEXT DEFAULT '{}',
        risk_score INTEGER DEFAULT 0,
        complexity TEXT DEFAULT 'medium',
        error TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS goals (
        id TEXT PRIMARY KEY,
        text TEXT,
        mode TEXT,
        priority INTEGER DEFAULT 2,
        status TEXT DEFAULT 'pending',
        result TEXT DEFAULT '',
        created_at REAL,
        started_at REAL,
        completed_at REAL,
        tags TEXT
    );
    """)
    conn.commit()


def get_db() -> sqlite3.Connection | None:
    """Retourne la connexion DB ou None si SQLite indisponible (fail-open)."""
    try:
        return _get_connection()
    except Exception:
        return None


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor | None:
    """Exécute une requête SQL. Retourne None si SQLite indisponible."""
    db = get_db()
    if db is None:
        return None
    try:
        with _lock:
            cur = db.execute(sql, params)
            db.commit()
            return cur
    except Exception:
        return None


def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    """Exécute une SELECT et retourne une liste de dicts."""
    db = get_db()
    if db is None:
        return []
    try:
        with _lock:
            cur = db.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    """Exécute une SELECT et retourne un seul dict ou None."""
    db = get_db()
    if db is None:
        return None
    try:
        with _lock:
            cur = db.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


# ── Helpers JSON pour les champs sérialisés ────────────────────────────────

def dumps(obj) -> str:
    """Sérialise en JSON string."""
    if obj is None:
        return ""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def loads(s: str | None, default=None):
    """Désérialise depuis JSON string."""
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


def get_sqlite_path() -> Path:
    """Return the path to the SQLite database file.

    Used by orchestrator_v2 and improvement_memory for their
    SQLite fallback when asyncpg/Postgres is unavailable.
    """
    return _DB_PATH


def reset_singleton():
    """Réinitialise le singleton (utile pour les tests)."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                _silent_log.debug("suppressed_exception", src='db.py')
            _conn = None
