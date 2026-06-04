"""fts_recall — rappel plein-texte inter-sessions via SQLite FTS5 (Axe 2, Hermes).

Couche de recall **légère et additive** : complète le vectoriel (qdrant) par une
recherche plein-texte rapide, sans dépendance externe (sqlite3 + FTS5 sont dans
la stdlib CPython). Conçue pour être branchée plus tard sur `MemoryBus.search`
(opt-in) — n'altère aucun backend existant.

Dégrade proprement vers une recherche `LIKE` si FTS5 est indisponible.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


class FTSRecall:
    """Stockage + rappel plein-texte de courts mémos, persistant sur disque."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self.fts = _fts5_available(self._conn)
        self._init_schema()

    def _init_schema(self) -> None:
        if self.fts:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories "
                "USING fts5(content, kind, session_id UNINDEXED, ts UNINDEXED)"
            )
        else:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memories "
                "(content TEXT, kind TEXT, session_id TEXT, ts REAL)"
            )
        self._conn.commit()

    def add(self, content: str, kind: str = "note", session_id: str = "") -> bool:
        if not isinstance(content, str) or not content.strip():
            return False
        self._conn.execute(
            "INSERT INTO memories (content, kind, session_id, ts) VALUES (?, ?, ?, ?)",
            (content, kind, session_id, time.time()),
        )
        self._conn.commit()
        return True

    def search(self, query: str, limit: int = 5) -> list[dict]:
        if not isinstance(query, str) or not query.strip():
            return []
        limit = max(1, min(int(limit), 50))
        rows: list[sqlite3.Row]
        if self.fts:
            try:
                rows = self._conn.execute(
                    "SELECT content, kind, session_id, ts FROM memories "
                    "WHERE memories MATCH ? ORDER BY rank LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # requête FTS invalide (caractères spéciaux) → repli LIKE
                rows = self._like_search(query, limit)
        else:
            rows = self._like_search(query, limit)
        return [dict(r) for r in rows]

    def _like_search(self, query: str, limit: int) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT content, kind, session_id, ts FROM memories "
            "WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
