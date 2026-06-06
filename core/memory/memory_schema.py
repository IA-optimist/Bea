"""
core/memory/memory_schema.py — Standardized memory schema for Jarvis AI-OS.

Defines three memory tiers with SQLite persistence:
- Short-term (working memory): current mission context, expires after mission
- Episodic (recent history): mission results, tool outcomes, conversations
- Long-term (persistent): learned patterns, skills, tool performance, preferences

Does NOT replace MemoryFacade. Provides typed models consumed by MemoryFacade.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional


MemoryTier = Literal["SHORT_TERM", "EPISODIC", "LONG_TERM"]
MemoryType = Literal[
    "mission_context",   # SHORT_TERM: current mission state
    "tool_result",       # SHORT_TERM: recent tool outputs
    "mission_result",    # EPISODIC: completed mission outcomes
    "conversation",      # EPISODIC: interaction history
    "skill",             # LONG_TERM: learned procedural knowledge
    "tool_performance",  # LONG_TERM: tool reliability stats
    "preference",        # LONG_TERM: user preferences
    "lesson",            # LONG_TERM: improvement lessons learned
]


@dataclass
class MemoryEntry:
    """Standardized memory entry across all tiers."""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    tier: MemoryTier = "EPISODIC"
    memory_type: str = "mission_result"
    content: str = ""
    metadata: dict = field(default_factory=dict)
    mission_id: str = ""
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: Optional[float] = None  # None = permanent
    importance: float = 0.5  # 0.0 - 1.0
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return time.time() > self.timestamp + self.ttl_seconds

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_expired"] = self.is_expired
        return d


# Default TTLs per tier
TIER_DEFAULTS: dict[MemoryTier, dict] = {
    "SHORT_TERM": {"ttl_seconds": 300, "max_entries": 100},
    "EPISODIC": {"ttl_seconds": 86400 * 7, "max_entries": 1000},  # 7 days
    "LONG_TERM": {"ttl_seconds": None, "max_entries": 10000},
}

# Persistence path — in workspace volume so it survives container recreate
_DB_PATH = os.environ.get(
    "JARVIS_MEMORY_DB",
    os.path.join(os.environ.get("JARVIS_ROOT", "/opt/jarvismax"), "workspace", "memory.db")
)


def _ensure_dir(path: str):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


class MemoryStore:
    """
    SQLite-backed memory store with tier-based TTL, deduplication, and limits.

    Falls back to in-memory if SQLite init fails (e.g., read-only FS in tests).
    Maintains full backward compatibility with the dict-based interface.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS memories (
        entry_id TEXT PRIMARY KEY,
        tier TEXT NOT NULL,
        memory_type TEXT NOT NULL DEFAULT 'mission_result',
        content TEXT NOT NULL DEFAULT '',
        metadata TEXT NOT NULL DEFAULT '{}',
        mission_id TEXT NOT NULL DEFAULT '',
        trace_id TEXT NOT NULL DEFAULT '',
        timestamp REAL NOT NULL,
        ttl_seconds REAL,
        importance REAL NOT NULL DEFAULT 0.5,
        access_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier);
    CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
    CREATE INDEX IF NOT EXISTS idx_memories_mission ON memories(mission_id);
    CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
    """

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or _DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._fallback: dict[str, MemoryEntry] = {}  # in-memory fallback
        self._persistent = False
        self._init_db()

    def _init_db(self):
        try:
            _ensure_dir(self._db_path)
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=10.0,  # wait up to 10s for locks
            )
            self._conn.row_factory = sqlite3.Row
            # WAL mode: concurrent reads + crash-safe writes
            self._conn.execute("PRAGMA journal_mode=WAL")
            # Synchronous NORMAL: good balance of safety vs speed
            self._conn.execute("PRAGMA synchronous=NORMAL")
            # Busy timeout: wait instead of failing on lock
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(self._SCHEMA)
            self._persistent = True
        except Exception:
            # Fallback to in-memory (for tests, read-only FS)
            self._persistent = False

    def integrity_check(self) -> dict:
        """Run SQLite integrity check. Call at startup."""
        if not self._persistent:
            return {"ok": True, "mode": "in-memory"}
        try:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            wal = self._conn.execute("PRAGMA journal_mode").fetchone()[0]
            page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
            page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
            size_bytes = page_count * page_size
            return {
                "ok": result == "ok",
                "integrity": result,
                "journal_mode": wal,
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / 1048576, 2),
                "path": self._db_path,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:100]}

    @property
    def is_persistent(self) -> bool:
        return self._persistent

    # ── Backward compat: _entries property ────────────────────────────────
    @property
    def _entries(self) -> dict[str, MemoryEntry]:
        """Backward compatibility — returns all non-expired entries as dict."""
        if not self._persistent:
            return self._fallback
        entries = {}
        for row in self._conn.execute("SELECT * FROM memories"):
            e = self._row_to_entry(row)
            entries[e.entry_id] = e
        return entries

    def _row_to_entry(self, row) -> MemoryEntry:
        return MemoryEntry(
            entry_id=row["entry_id"],
            tier=row["tier"],
            memory_type=row["memory_type"],
            content=row["content"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            mission_id=row["mission_id"],
            trace_id=row["trace_id"],
            timestamp=row["timestamp"],
            ttl_seconds=row["ttl_seconds"],
            importance=row["importance"],
            access_count=row["access_count"],
        )

    _lock = __import__("threading").Lock()

    def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry. Returns entry_id. Thread-safe."""
        if entry.ttl_seconds is None and entry.tier in TIER_DEFAULTS:
            entry.ttl_seconds = TIER_DEFAULTS[entry.tier].get("ttl_seconds")

        if not self._persistent:
            self._fallback[entry.entry_id] = entry
            return entry.entry_id

        with self._lock:
            self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (entry_id, tier, memory_type, content, metadata, mission_id,
                trace_id, timestamp, ttl_seconds, importance, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.entry_id, entry.tier, entry.memory_type, entry.content,
             json.dumps(entry.metadata), entry.mission_id, entry.trace_id,
             entry.timestamp, entry.ttl_seconds, entry.importance, entry.access_count)
        )
            self._conn.commit()
            return entry.entry_id

    def retrieve(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve by ID. Returns None if not found or expired."""
        if not self._persistent:
            e = self._fallback.get(entry_id)
            if e and not e.is_expired:
                e.access_count += 1
                return e
            return None

        row = self._conn.execute(
            "SELECT * FROM memories WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return None
        e = self._row_to_entry(row)
        if e.is_expired:
            return None
        self._conn.execute(
            "UPDATE memories SET access_count = access_count + 1 WHERE entry_id = ?",
            (entry_id,)
        )
        self._conn.commit()
        return e

    def search(self, memory_type: str = "", tier: str = "",
               mission_id: str = "", limit: int = 20) -> list[MemoryEntry]:
        """Search entries by type, tier, or mission."""
        if not self._persistent:
            results = []
            for entry in self._fallback.values():
                if entry.is_expired: continue
                if memory_type and entry.memory_type != memory_type: continue
                if tier and entry.tier != tier: continue
                if mission_id and entry.mission_id != mission_id: continue
                results.append(entry)
            results.sort(key=lambda e: e.importance, reverse=True)
            return results[:limit]

        conditions = ["1=1"]
        params = []
        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)
        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        if mission_id:
            conditions.append("mission_id = ?")
            params.append(mission_id)

        where = " AND ".join(conditions)
        # `where` only contains literal column-name comparisons
        # (`"memory_type = ?"`, etc.) ; values pass via SQLite `?` placeholders.
        _q = f"SELECT * FROM memories WHERE {where} ORDER BY importance DESC LIMIT ?"  # nosec B608  # noqa: S608
        rows = self._conn.execute(_q, params + [limit]).fetchall()
        return [self._row_to_entry(r) for r in rows if not self._row_to_entry(r).is_expired]

    def cleanup(self) -> int:
        """Remove expired entries. Returns count removed."""
        if not self._persistent:
            expired = [eid for eid, e in self._fallback.items() if e.is_expired]
            for eid in expired:
                del self._fallback[eid]
            return len(expired)

        now = time.time()
        cursor = self._conn.execute(
            "DELETE FROM memories WHERE ttl_seconds IS NOT NULL AND (timestamp + ttl_seconds) < ?",
            (now,)
        )
        self._conn.commit()
        return cursor.rowcount

    def enforce_limits(self) -> dict:
        """Enforce tier-based entry limits. Removes oldest excess entries."""
        removed_total = 0
        details = {}
        for tier, defaults in TIER_DEFAULTS.items():
            max_entries = defaults.get("max_entries", 10000)

            if not self._persistent:
                tier_entries = sorted(
                    [e for e in self._fallback.values() if e.tier == tier],
                    key=lambda e: e.timestamp,
                )
                excess = len(tier_entries) - max_entries
                if excess > 0:
                    for e in tier_entries[:excess]:
                        del self._fallback[e.entry_id]
                    removed_total += excess
                details[tier] = {"count": len(tier_entries) - max(excess, 0), "limit": max_entries, "removed": max(excess, 0)}
            else:
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE tier = ?", (tier,)
                ).fetchone()[0]
                excess = count - max_entries
                if excess > 0:
                    self._conn.execute(
                        "DELETE FROM memories WHERE entry_id IN ("
                        "  SELECT entry_id FROM memories WHERE tier = ? ORDER BY timestamp ASC LIMIT ?"
                        ")", (tier, excess)
                    )
                    self._conn.commit()
                    removed_total += excess
                details[tier] = {"count": count - max(excess, 0), "limit": max_entries, "removed": max(excess, 0)}

        return {"removed": removed_total, "by_tier": details}

    def summarize_tier(self, tier: MemoryTier) -> dict:
        """Stats for a memory tier."""
        if not self._persistent:
            entries = [e for e in self._fallback.values() if e.tier == tier and not e.is_expired]
            return {
                "tier": tier,
                "count": len(entries),
                "avg_importance": round(sum(e.importance for e in entries) / max(len(entries), 1), 2),
                "oldest": min((e.timestamp for e in entries), default=0),
                "newest": max((e.timestamp for e in entries), default=0),
            }

        row = self._conn.execute(
            "SELECT COUNT(*) as cnt, AVG(importance) as avg_imp, "
            "MIN(timestamp) as oldest, MAX(timestamp) as newest "
            "FROM memories WHERE tier = ?", (tier,)
        ).fetchone()
        return {
            "tier": tier,
            "count": row["cnt"] or 0,
            "avg_importance": round(row["avg_imp"] or 0, 2),
            "oldest": row["oldest"] or 0,
            "newest": row["newest"] or 0,
        }

    def stats(self) -> dict:
        """Overall memory stats."""
        if not self._persistent:
            total = len(self._fallback)
            expired = sum(1 for e in self._fallback.values() if e.is_expired)
        else:
            total = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            now = time.time()
            expired = self._conn.execute(
                "SELECT COUNT(*) FROM memories WHERE ttl_seconds IS NOT NULL AND (timestamp + ttl_seconds) < ?",
                (now,)
            ).fetchone()[0]

        return {
            "total": total,
            "active": total - expired,
            "expired": expired,
            "persistent": self._persistent,
            "db_path": self._db_path if self._persistent else "in-memory",
            "by_tier": {
                tier: self.summarize_tier(tier)
                for tier in ("SHORT_TERM", "EPISODIC", "LONG_TERM")
            },
        }


_store: MemoryStore | None = None

def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
