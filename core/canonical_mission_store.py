"""
canonical_mission_store.py — SQLite persistence for canonical missions.

Stores CanonicalMissionContext so that /api/v3/missions state survives restarts.

Design:
    - Single table: canonical_missions
    - Full context stored as JSON blob + key fields for filtering
    - WAL mode for concurrency safety
    - Graceful degradation: if SQLite is unavailable, store is a no-op
    - Never raises: all methods catch and log exceptions

Usage:
    store = CanonicalMissionStore()              # defaults to workspace/canonical_missions.db
    store = CanonicalMissionStore(db_path=path)  # custom path
    store.save(ctx)
    ctx = store.get("abc123")
    all_ctxs = store.load_all()
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)
_silent_log = log

from core.canonical_types import (
    CanonicalMissionContext,
    CanonicalMissionStatus,
    CanonicalRiskLevel,
)

_DEFAULT_DB_NAME = "canonical_missions.db"


def _default_db_path() -> Path:
    """Resolve default DB path via settings or fallback to workspace/ or /tmp/."""
    candidates = []
    try:
        from config.settings import get_settings
        s = get_settings()
        candidates.append(Path(s.workspace_dir))
    except Exception as _exc:
        log.warning("swallowed_exception", action="canonical_mission_store_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    candidates.append(Path("workspace"))

    for db_dir in candidates:
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
            # Quick write-test: ensure directory is actually writable
            test_path = db_dir / ".write_test"
            test_path.touch()
            test_path.unlink()
            return db_dir / _DEFAULT_DB_NAME
        except Exception:
            log.debug("swallowed_exception", exc_info=True)
            continue

    # Last-resort fallback: use /tmp (survives the session but not reboots)
    fallback = Path("/tmp/jarvismax_canonical_missions.db")  # nosec B108 — documented last-resort path; preferred paths checked above.
    log.warning("canonical_mission_store.using_tmp_fallback", path=str(fallback))
    return fallback


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS canonical_missions (
    mission_id    TEXT PRIMARY KEY,
    goal          TEXT NOT NULL,
    status        TEXT NOT NULL,
    risk_level    TEXT NOT NULL DEFAULT 'WRITE_LOW',
    error         TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT '',
    source_system TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    context_json  TEXT NOT NULL
)
"""

# Indexes run as separate statements — sqlite3.execute() only accepts one statement at a time.
_CREATE_INDEX_CREATED_AT = """
CREATE INDEX IF NOT EXISTS idx_canonical_missions_created_at
    ON canonical_missions(created_at DESC)
"""

_CREATE_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_canonical_missions_status
    ON canonical_missions(status)
"""

_CREATE_TABLE_PG = """
CREATE TABLE IF NOT EXISTS canonical_missions (
    mission_id    TEXT PRIMARY KEY,
    goal          TEXT NOT NULL,
    status        TEXT NOT NULL,
    risk_level    TEXT NOT NULL DEFAULT 'WRITE_LOW',
    error         TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT '',
    source_system TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    context_json  TEXT NOT NULL
)
"""

_UPSERT = """
INSERT INTO canonical_missions
    (mission_id, goal, status, risk_level, error, result, source_system, created_at, updated_at, context_json)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(mission_id) DO UPDATE SET
    goal          = excluded.goal,
    status        = excluded.status,
    risk_level    = excluded.risk_level,
    error         = excluded.error,
    result        = excluded.result,
    source_system = excluded.source_system,
    updated_at    = excluded.updated_at,
    context_json  = excluded.context_json;
"""


class CanonicalMissionStore:
    """
    Persistent store for CanonicalMissionContext.
    Postgres primary (via settings.database_url), SQLite fallback.
    All methods are synchronous and safe to call from any thread.
    Never raises — errors are logged and the store degrades gracefully.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path: Optional[Path] = None
        self._ok = False
        self._pg_dsn: Optional[str] = None

        # Try Postgres first — UNLESS the caller explicitly requested a SQLite
        # path. Tests pass tmpfile paths and expect SQLite behaviour; if we
        # silently routed their writes to an opportunistically-available
        # Postgres (e.g. DATABASE_URL set in CI), every read-back assertion
        # would fail (audit S6.E, 2026-05-19).
        if db_path is None:
            try:
                from config.settings import Settings
                dsn = Settings().database_url
                if dsn:
                    import psycopg2
                    conn = psycopg2.connect(dsn)
                    conn.autocommit = True
                    conn.cursor().execute(_CREATE_TABLE_PG)
                    conn.close()
                    self._pg_dsn = dsn
                    self._ok = True
                    log.info("canonical_mission_store.ready", backend="postgres")
                    return
            except Exception as exc:
                log.debug("canonical_mission_store.pg_skipped", err=str(exc)[:80])

        # SQLite fallback
        try:
            explicit = db_path is not None
            path = db_path or _default_db_path()
            self._db_path = Path(path)
            # Pre-check : ensure parent directory exists AND is writable before
            # attempting sqlite3.connect (qui crée le fichier paresseusement et
            # ne lève pas jusqu'à la première écriture SQL). Pour les chemins
            # explicites, on NE crée PAS le parent — c'est une erreur utilisateur
            # (ex. chemin mal-configuré). Pour les défauts, mkdir est OK.
            parent = self._db_path.parent
            if not parent.exists():
                if explicit:
                    raise OSError(
                        f"parent directory does not exist: {parent} "
                        f"(explicit db_path must have writable parent)"
                    )
                parent.mkdir(parents=True, exist_ok=True)
            # Quick write-test (même pattern que _default_db_path).
            _probe = parent / ".canonical_write_test"
            _probe.touch()
            _probe.unlink()
            self._init_db()
            self._ok = True
            log.info("canonical_mission_store.ready", db_path=str(self._db_path))
        except Exception as exc:
            log.warning(
                "canonical_mission_store.init_failed",
                err=str(exc)[:200],
                db_path=str(db_path),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX_CREATED_AT)
            conn.execute(_CREATE_INDEX_STATUS)

    # ── Write ───────────────────────────────────────────────────────────────

    def save(self, ctx: CanonicalMissionContext) -> None:
        """Persist a CanonicalMissionContext. Upserts on conflict."""
        if not self._ok:
            return
        try:
            d = ctx.to_dict()
            context_json = json.dumps(d)
            values = (
                ctx.mission_id,
                ctx.goal[:500],
                ctx.status.value,
                ctx.risk_level.value,
                (ctx.error or "")[:500],
                (ctx.result or "")[:2000],
                ctx.source_system or "",
                ctx.created_at,
                ctx.updated_at,
                context_json,
            )
            if self._pg_dsn:
                import datetime as _dt
                # PG expects timestamptz, not float — convert unix timestamps
                vals_list = list(values)
                # created_at = index 7, updated_at = index 8
                for idx in (7, 8):
                    v = vals_list[idx]
                    if isinstance(v, (int, float)):
                        vals_list[idx] = _dt.datetime.fromtimestamp(v, tz=_dt.timezone.utc)
                values = tuple(vals_list)
                self._save_pg(values)
            elif self._db_path:
                with self._connect() as conn:
                    conn.execute(_UPSERT, values)
        except Exception as exc:
            log.warning(
                "canonical_mission_store.save_failed",
                mission_id=getattr(ctx, "mission_id", "?"),
                err=str(exc)[:200],
            )

    def _save_pg(self, values: tuple) -> None:
        import psycopg2
        conn = psycopg2.connect(self._pg_dsn)
        conn.autocommit = True
        conn.cursor().execute(
            """INSERT INTO canonical_missions
               (mission_id, goal, status, risk_level, error, result,
                source_system, created_at, updated_at, context_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(mission_id) DO UPDATE SET
                goal=EXCLUDED.goal, status=EXCLUDED.status,
                risk_level=EXCLUDED.risk_level, error=EXCLUDED.error,
                result=EXCLUDED.result, source_system=EXCLUDED.source_system,
                updated_at=EXCLUDED.updated_at, context_json=EXCLUDED.context_json""",
            values,
        )
        conn.close()

    # ── Read ────────────────────────────────────────────────────────────────

    def get(self, mission_id: str) -> Optional[CanonicalMissionContext]:
        """Fetch a single mission by ID. Returns None if not found."""
        if not self._ok:
            return None
        try:
            if self._pg_dsn:
                import psycopg2
                conn = psycopg2.connect(self._pg_dsn)
                cur = conn.cursor()
                cur.execute("SELECT context_json FROM canonical_missions WHERE mission_id = %s", (mission_id,))
                row = cur.fetchone()
                conn.close()
            elif self._db_path:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT context_json FROM canonical_missions WHERE mission_id = ?",
                        (mission_id,),
                    ).fetchone()
            else:
                return None
            if row:
                return _row_to_ctx(row[0])
        except Exception as exc:
            log.warning("canonical_mission_store.get_failed", mission_id=mission_id, err=str(exc)[:200])
        return None

    def load_all(self, limit: int = 500) -> list[CanonicalMissionContext]:
        """Load all missions, ordered by created_at DESC. Used on startup."""
        if not self._ok:
            return []
        try:
            if self._pg_dsn:
                import psycopg2
                conn = psycopg2.connect(self._pg_dsn)
                cur = conn.cursor()
                cur.execute("SELECT context_json FROM canonical_missions ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
                conn.close()
            elif self._db_path:
                with self._connect() as conn:
                    rows = conn.execute(
                        "SELECT context_json FROM canonical_missions ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
            else:
                return []
            result = []
            for (json_str,) in rows:
                ctx = _row_to_ctx(json_str)
                if ctx:
                    result.append(ctx)
            return result
        except Exception as exc:
            log.warning("canonical_mission_store.load_all_failed", err=str(exc)[:200])
        return []

    def count(self) -> int:
        """Return total number of missions in store."""
        if not self._ok:
            return 0
        try:
            if self._pg_dsn:
                import psycopg2
                conn = psycopg2.connect(self._pg_dsn)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM canonical_missions")
                row = cur.fetchone()
                conn.close()
            elif self._db_path:
                with self._connect() as conn:
                    row = conn.execute("SELECT COUNT(*) FROM canonical_missions").fetchone()
            else:
                return 0
            return row[0] if row else 0
        except Exception:
            return 0


# ── Deserialization helper ──────────────────────────────────────────────────


def _row_to_ctx(json_str) -> Optional[CanonicalMissionContext]:
    """Reconstruct CanonicalMissionContext from stored JSON."""
    try:
        # Handle both str (SQLite) and dict (PostgreSQL jsonb) inputs
        d = json_str if isinstance(json_str, dict) else json.loads(json_str)
        return CanonicalMissionContext(
            mission_id=d["mission_id"],
            goal=d.get("goal", ""),
            status=_parse_status(d.get("status", "CREATED")),
            risk_level=_parse_risk(d.get("risk_level", "WRITE_LOW")),
            intent=d.get("intent", ""),
            domain=d.get("domain", "general"),
            plan_summary=d.get("plan_summary", ""),
            agents=d.get("agents", []),
            error=d.get("error", ""),
            result=d.get("result", ""),
            source_system=d.get("source_system", ""),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            metadata=d.get("metadata", {}),
        )
    except Exception as exc:
        log.warning("canonical_mission_store.deserialize_failed", err=str(exc)[:200])
        return None


def _parse_status(val: str) -> CanonicalMissionStatus:
    try:
        return CanonicalMissionStatus(val)
    except ValueError:
        return CanonicalMissionStatus.CREATED


def _parse_risk(val: str) -> CanonicalRiskLevel:
    try:
        return CanonicalRiskLevel(val)
    except ValueError:
        return CanonicalRiskLevel.WRITE_LOW
