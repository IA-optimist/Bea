"""
core/memory/operational_memory.py — Structured operational memory store.

Lightweight SQLite-backed store for MemoryItem objects.
- Additive: does not replace MemoryStore, MemoryFacade, MemoryBus or Qdrant.
- Searchable by type, status, related_files, tags and text (LIKE / FTS optional).
- Falls back to in-memory storage if SQLite is unavailable (tests, read-only FS).
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from typing import Any, Iterable

from core.memory.memory_item import MemoryItem, MemoryItemStatus, MemoryItemType


def _default_db() -> str:
    # Read at call time so --isolated mode can override BEA_OPERATIONAL_MEMORY_DB
    # after module import without stale path being captured at import time.
    return os.environ.get(
        "BEA_OPERATIONAL_MEMORY_DB",
        os.path.join(os.environ.get("BEA_ROOT", "/opt/beamax"), "workspace", "operational_memory.db"),
    )


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


class OperationalMemoryStore:
    """
    SQLite store for MemoryItem objects.

    Schema keeps relations compact:
        - related_files stored as JSON list in column
        - related_tests stored as JSON list in column
        - tags stored as JSON list in column, plus a separate tags table for joins
        - fts enabled when sqlite3 supports FTS5
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS memory_items (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        confidence REAL NOT NULL DEFAULT 0.5,
        source TEXT NOT NULL DEFAULT '',
        related_files TEXT NOT NULL DEFAULT '[]',
        related_tests TEXT NOT NULL DEFAULT '[]',
        tags TEXT NOT NULL DEFAULT '[]',
        supersedes TEXT NOT NULL DEFAULT '[]',
        superseded_by TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_memory_items_type ON memory_items(type);
    CREATE INDEX IF NOT EXISTS idx_memory_items_status ON memory_items(status);
    CREATE INDEX IF NOT EXISTS idx_memory_items_source ON memory_items(source);
    CREATE INDEX IF NOT EXISTS idx_memory_items_updated ON memory_items(updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_memory_items_confidence ON memory_items(confidence DESC);
    """

    _TAGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS memory_item_tags (
        item_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (item_id, tag),
        FOREIGN KEY (item_id) REFERENCES memory_items(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_memory_item_tags_tag ON memory_item_tags(tag);
    """

    def __init__(self, db_path: str = "") -> None:
        self.db_path = db_path or _default_db()
        if self.db_path != ":memory:":
            _ensure_dir(self.db_path)
        self._conn: sqlite3.Connection | None = None
        self._fallback: dict[str, MemoryItem] = {}
        self._persistent = False
        self._fts = False
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript("PRAGMA foreign_keys = ON;" + self._SCHEMA + self._TAGS_SCHEMA)
            self._try_init_fts()
            self._persistent = True
        except Exception:
            self._persistent = False
            self._conn = None

    def _try_init_fts(self) -> None:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(id UNINDEXED, content)")
            self._fts = True
        except sqlite3.OperationalError:
            self._fts = False

    # ── Core helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _jlist(value: Iterable[str]) -> str:
        return json.dumps(list(value))

    @staticmethod
    def _jparse(value: str) -> list[str]:
        try:
            return list(json.loads(value))
        except Exception:
            return []

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem.from_dict({
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "confidence": row["confidence"],
            "source": row["source"],
            "related_files": self._jparse(row["related_files"]),
            "related_tests": self._jparse(row["related_tests"]),
            "tags": self._jparse(row["tags"]),
            "supersedes": self._jparse(row["supersedes"]),
            "superseded_by": row["superseded_by"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    def _write_item(self, item: MemoryItem) -> None:
        if not self._persistent or not self._conn:
            self._fallback[item.id] = item
            return
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO memory_items
                   (id, type, title, content, status, confidence, source,
                    related_files, related_tests, tags, supersedes, superseded_by,
                    metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.type.value, item.title, item.content,
                    item.status.value, item.confidence, item.source,
                    self._jlist(item.related_files), self._jlist(item.related_tests),
                    self._jlist(item.tags), self._jlist(item.supersedes),
                    item.superseded_by, json.dumps(item.metadata),
                    item.created_at, item.updated_at,
                ),
            )
            # Refresh tags join table
            self._conn.execute("DELETE FROM memory_item_tags WHERE item_id = ?", (item.id,))
            for tag in item.tags:
                self._conn.execute(
                    "INSERT OR IGNORE INTO memory_item_tags (item_id, tag) VALUES (?, ?)",
                    (item.id, tag),
                )
            # FTS mirror: UPSERT is not supported for virtual tables.
            if self._fts:
                self._conn.execute("DELETE FROM memory_items_fts WHERE id = ?", (item.id,))
                self._conn.execute(
                    "INSERT INTO memory_items_fts (id, content) VALUES (?, ?)",
                    (item.id, item.search_text),
                )
            self._conn.commit()

    _lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, item: MemoryItem) -> str:
        """Store or update a MemoryItem. Returns id."""
        item.bump_updated()
        self._write_item(item)
        return item.id

    def get(self, item_id: str) -> MemoryItem | None:
        """Retrieve by id."""
        if not self._persistent:
            return self._fallback.get(item_id)
        row = self._conn.execute("SELECT * FROM memory_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def search(
        self,
        type: MemoryItemType | str | None = None,
        status: MemoryItemStatus | str | None = None,
        tags: list[str] | None = None,
        related_files: list[str] | None = None,
        related_tests: list[str] | None = None,
        text_query: str = "",
        min_confidence: float = 0.0,
        prefer_active: bool = True,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """
        Search memory items by structured filters and/or text query.

        Matching rules:
            - type/status are exact matches
            - tags: all given tags must be present
            - related_files/related_tests: any given path must match a stored path
            - text_query: FTS5 when available, otherwise LIKE on title+content+tags
            - prefer_active: obsolete/replaced entries are deprioritized (not removed)
        """
        if not self._persistent:
            return self._search_fallback(
                type=type, status=status, tags=tags,
                related_files=related_files, related_tests=related_tests,
                text_query=text_query, min_confidence=min_confidence,
                prefer_active=prefer_active, limit=limit,
            )

        conditions = ["1=1"]
        params: list[Any] = []

        if type is not None:
            conditions.append("type = ?")
            params.append(type.value if isinstance(type, MemoryItemType) else type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value if isinstance(status, MemoryItemStatus) else status)
        if min_confidence:
            conditions.append("confidence >= ?")
            params.append(min_confidence)

        if tags:
            # Require each tag in tags array of the row (JSON contains)
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        if related_files:
            file_conds = []
            for rf in related_files:
                file_conds.append("related_files LIKE ?")
                params.append(f'%"{rf}"%')
            conditions.append("(" + " OR ".join(file_conds) + ")")

        if related_tests:
            test_conds = []
            for rt in related_tests:
                test_conds.append("related_tests LIKE ?")
                params.append(f'%"{rt}"%')
            conditions.append("(" + " OR ".join(test_conds) + ")")

        if text_query and text_query.strip():
            q = text_query.strip()
            if self._fts:
                try:
                    rows = self._conn.execute(
                        "SELECT id FROM memory_items_fts WHERE memory_items_fts MATCH ? ORDER BY rank LIMIT ?",
                        (q, limit * 5),
                    ).fetchall()
                    fts_ids = [r["id"] for r in rows]
                except sqlite3.OperationalError:
                    fts_ids = []
            if fts_ids:
                conditions.append(f"id IN ({','.join('?' for _ in fts_ids)})")
                params.extend(fts_ids)
            else:
                conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
                like = f"%{q}%"
                params.extend([like, like, like])

        where = " AND ".join(conditions)
        order = (
            "CASE WHEN status IN ('obsolete','replaced') THEN 1 ELSE 0 END ASC, "
            "confidence DESC, updated_at DESC"
        ) if prefer_active else "confidence DESC, updated_at DESC"

        # `where` and `order` only contain column-name literals; all values use `?` placeholders.
        query = f"SELECT * FROM memory_items WHERE {where} ORDER BY {order} LIMIT ?"  # nosec B608
        rows = self._conn.execute(query, params + [limit]).fetchall()
        return [self._row_to_item(r) for r in rows]

    def _search_fallback(
        self,
        type: MemoryItemType | str | None,
        status: MemoryItemStatus | str | None,
        tags: list[str] | None,
        related_files: list[str] | None,
        related_tests: list[str] | None,
        text_query: str,
        min_confidence: float,
        prefer_active: bool,
        limit: int,
    ) -> list[MemoryItem]:
        results = []
        for item in self._fallback.values():
            if type is not None:
                target = type.value if isinstance(type, MemoryItemType) else type
                if item.type.value != target:
                    continue
            if status is not None:
                target = status.value if isinstance(status, MemoryItemStatus) else status
                if item.status.value != target:
                    continue
            if min_confidence and item.confidence < min_confidence:
                continue
            if tags and not all(t in item.tags for t in tags):
                continue
            if related_files and not any(rf in item.related_files for rf in related_files):
                continue
            if related_tests and not any(rt in item.related_tests for rt in related_tests):
                continue
            if text_query:
                q = text_query.lower()
                hay = item.search_text.lower()
                if q not in hay:
                    continue
            results.append(item)
        if prefer_active:
            results.sort(key=lambda i: (0 if i.is_usable() else 1, -i.confidence, -i.updated_at))
        else:
            results.sort(key=lambda i: (-i.confidence, -i.updated_at))
        return results[:limit]

    # ── Ranking layer ─────────────────────────────────────────────────────────

    DEFAULT_WEIGHTS: dict[str, float] = {
        "active": 1.0,
        "related_file_match": 0.8,
        "related_test_match": 0.5,
        "tag_match": 0.4,
        "confidence": 0.6,
        "trusted_source": 0.2,
        "recency": 0.3,
        "type_relevance": 0.3,
        "obsolete": -2.0,
        "replaced": -2.0,
        "unverified": -0.5,
        "low_importance": -0.7,
        "no_source": -0.4,
        "private_joke": -1.5,
        "old": -0.2,
    }

    TRUSTED_SOURCES: frozenset[str] = frozenset({
        "audit", "security/policy", "docs/decisions", "kernel",
        "test", "ci", "repo_map", "bea_eval",
    })

    LIGHT_CONTEXT_KEYWORDS: frozenset[str] = frozenset({
        "fun", "joke", "joke", "humour", "humor", "private", "personal",
        "anecdote", "trivia", "light", "max", "béa", "romance",
    })

    def _score_item(
        self,
        item: MemoryItem,
        query_tokens: set[str],
        related_files: list[str],
        related_tests: list[str],
        tags: list[str],
        weights: dict[str, float] | None,
        now: float,
        context_type: str = "",
    ) -> float:
        """Compute a simple relevance score for a memory item."""
        w = weights or self.DEFAULT_WEIGHTS
        score = 0.0

        # Status
        if item.status == MemoryItemStatus.ACTIVE:
            score += w["active"]
        elif item.status == MemoryItemStatus.DANGEROUS:
            # Risks are surfaced but not boosted over active facts unless requested.
            score += w.get("dangerous", 0.0)
        elif item.status == MemoryItemStatus.OBSOLETE:
            score += w["obsolete"]
        elif item.status == MemoryItemStatus.REPLACED:
            score += w["replaced"]
        elif item.status == MemoryItemStatus.UNVERIFIED:
            score += w["unverified"]

        # Confidence
        score += item.confidence * w["confidence"]

        # Related files / tests
        if related_files:
            matches = sum(1 for rf in related_files if rf in item.related_files)
            if matches:
                score += min(1.0, matches / len(related_files)) * w["related_file_match"]
        if related_tests:
            test_matches = sum(1 for rt in related_tests if rt in item.related_tests)
            if test_matches:
                score += min(1.0, test_matches / len(related_tests)) * w["related_test_match"]
        if tags:
            tag_matches = sum(1 for t in tags if t in item.tags)
            if tag_matches:
                score += min(1.0, tag_matches / len(tags)) * w["tag_match"]

        # Text query overlap
        if query_tokens:
            item_tokens = set(item.search_text.lower().split())
            overlap = len(query_tokens & item_tokens)
            score += min(1.0, overlap / max(len(query_tokens), 1)) * w.get("text_match", 0.3)

        # Trusted source
        if item.source and any(s in item.source.lower() for s in self.TRUSTED_SOURCES):
            score += w["trusted_source"]
        elif not item.source:
            score += w["no_source"]

        # Recency (30 days half-life)
        age_days = max(0.0, (now - item.updated_at) / 86400)
        recency = math.exp(-age_days / 30.0)
        score += recency * w["recency"]
        if age_days > 365:
            score += w["old"]

        # Low importance penalty (unless explicitly light context)
        if item.metadata.get("importance") == "low":
            if not self._is_light_context(query_tokens, context_type=context_type):
                score += w["low_importance"]

        # Private joke / fun fact suppression for serious missions
        is_private = item.is_not_for_decision
        is_light = self._is_light_context(query_tokens, context_type=context_type)
        if is_private and not is_light:
            score += w["private_joke"]
        elif is_private and is_light:
            # Keep slightly negative so they are not artificially promoted
            score += w.get("private_joke_light", -0.1)

        return round(score, 3)

    @classmethod
    def _is_light_context(cls, query_tokens: set[str], *, context_type: str = "") -> bool:
        """Detect light/humorous/personal missions that may surface fun facts."""
        all_tokens = set(query_tokens)
        if context_type:
            all_tokens.update(context_type.lower().split())
        return any(t in cls.LIGHT_CONTEXT_KEYWORDS for t in all_tokens)

    def ranked_search(
        self,
        query: str = "",
        type: MemoryItemType | str | None = None,
        status: MemoryItemStatus | str | None = None,
        tags: list[str] | None = None,
        related_files: list[str] | None = None,
        related_tests: list[str] | None = None,
        min_confidence: float = 0.0,
        include_obsolete: bool = False,
        include_private_joke: bool = False,
        weights: dict[str, float] | None = None,
        limit: int = 20,
        pool_multiplier: int = 4,
    ) -> list[tuple[MemoryItem, float]]:
        """
        Ranked search returning (item, score) sorted by descending score.

        Always favors active, high-confidence, recently updated memories with
        matching files/tags. Obsolete/replaced/unverified are deprioritized.
        Private jokes and fun facts are only surfaced for light/humorous/personal
        contexts unless include_private_joke=True.
        """
        tags = tags or []
        related_files = related_files or []
        related_tests = related_tests or []
        query_tokens = {t for t in query.lower().split() if len(t) >= 2}
        now = __import__("time").time()

        # Fetch a larger pool than requested so ranking can surface the best N.
        # Use structured filters first; full-text query is applied only when no
        # structured filters are supplied, because a long mission phrase rarely
        # matches exact FTS/LIKE patterns in the existing memories.
        structured_pool: list[MemoryItem] = []
        has_structured_filters = any([
            type is not None,
            status is not None,
            tags,
            related_files,
            related_tests,
            min_confidence,
        ])

        if has_structured_filters:
            structured_pool = self.search(
                type=type,
                status=status,
                tags=tags if tags else None,
                related_files=related_files if related_files else None,
                related_tests=related_tests if related_tests else None,
                min_confidence=min_confidence,
                prefer_active=False,
                limit=max(limit * pool_multiplier, 50),
            )

        text_pool: list[MemoryItem] = []
        if query.strip() and (not has_structured_filters or len(structured_pool) < limit):
            text_pool = self.search(
                text_query=query,
                type=type,
                status=status,
                min_confidence=min_confidence,
                prefer_active=False,
                limit=max(limit * pool_multiplier, 50),
            )

        seen = {item.id for item in structured_pool}
        pool = list(structured_pool)
        for item in text_pool:
            if item.id not in seen:
                pool.append(item)

        scored: list[tuple[float, MemoryItem]] = []
        context_type = str(type.value if isinstance(type, MemoryItemType) else type)
        for item in pool:
            if not include_obsolete and item.status in (MemoryItemStatus.OBSOLETE, MemoryItemStatus.REPLACED):
                continue
            s = self._score_item(item, query_tokens, related_files, related_tests, tags, weights, now, context_type=context_type)
            # Hard filter: private jokes and fun facts dropped for serious contexts
            if not include_private_joke and item.is_not_for_decision and not self._is_light_context(query_tokens, context_type=context_type):
                continue
            scored.append((s, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(item, score) for score, item in scored[:limit]]

    def search_best(
        self,
        query: str = "",
        type: MemoryItemType | str | None = None,
        tags: list[str] | None = None,
        related_files: list[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Convenience: return only the items from ranked_search."""
        return [item for item, _ in self.ranked_search(
            query=query, type=type, tags=tags, related_files=related_files, limit=limit,
        )]

    def by_file(self, path: str, limit: int = 20) -> list[MemoryItem]:
        """All memory items related to a given file path."""
        return self.search(related_files=[path], limit=limit)

    def by_test(self, path: str, limit: int = 20) -> list[MemoryItem]:
        """All memory items related to a given test path."""
        return self.search(related_tests=[path], limit=limit)

    def supersede(self, old_id: str, new_id: str) -> bool:
        """Mark old_id as obsolete and point it to new_id."""
        old = self.get(old_id)
        if not old:
            return False
        old.status = MemoryItemStatus.OBSOLETE
        old.superseded_by = new_id
        new = self.get(new_id)
        if new and old_id not in new.supersedes:
            new.supersedes.append(old_id)
            self.add(new)
        self.add(old)
        return True

    def count(self) -> int:
        if not self._persistent:
            return len(self._fallback)
        return self._conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]

    def stats(self) -> dict[str, Any]:
        if not self._persistent:
            return {
                "persistent": False,
                "total": len(self._fallback),
                "by_type": {},
            }
        total = self._conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
        by_type = {
            row["type"]: row["cnt"]
            for row in self._conn.execute("SELECT type, COUNT(*) as cnt FROM memory_items GROUP BY type")
        }
        by_status = {
            row["status"]: row["cnt"]
            for row in self._conn.execute("SELECT status, COUNT(*) as cnt FROM memory_items GROUP BY status")
        }
        return {
            "persistent": True,
            "db_path": self.db_path,
            "total": total,
            "fts": self._fts,
            "by_type": by_type,
            "by_status": by_status,
        }

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass


_store: OperationalMemoryStore | None = None


def get_operational_memory_store(db_path: str = "") -> OperationalMemoryStore:
    """Singleton accessor for OperationalMemoryStore."""
    global _store
    if _store is None:
        _store = OperationalMemoryStore(db_path=db_path)
    return _store


def reset_operational_memory_store() -> None:
    """Reset singleton, mainly for tests."""
    global _store
    _store = None
