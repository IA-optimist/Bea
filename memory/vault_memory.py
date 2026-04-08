"""
JARVIS MAX — Vault Memory v2
Mémoire structurée, fiable et exploitable.

Format d'entrée :
{
  "id":          "uuid8",
  "type":        "pattern | error | fix | insight | business | code",
  "content":     "La connaissance elle-même (principal, lisible)",
  "source":      "URL, agent, expérience, test",
  "confidence":  0.0 → 1.0,
  "usage_count": 0,
  "last_used":   "ISO timestamp ou null",
  "tags":        ["python", "async", "timeout"],
  "related_to":  ["entry_id_1", "entry_id_2"],
  "valid":       true
}

Règles d'intégrité :
  - Déduplication Jaccard 0.60 sur content
  - confidence < 0.30 → rejetée
  - valid=False → exclue des résultats (soft-delete)
  - Scoring : +0.05 par usage_success, -0.10 par usage_failure
  - TTL : expiration par champ expires_at (epoch float)

Persistance : SQLite (workspace/jarvismax.db) avec fallback JSON
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger()

_STORAGE_PATH      = Path("workspace/vault_memory.json")
_MAX_ENTRIES       = 2000
_MIN_CONFIDENCE    = 0.30   # seuil minimal d'acceptation
_DEDUP_THRESHOLD   = 0.60   # Jaccard pour déduplication
_SCORE_HIT         = 0.05   # boost score par usage réussi
_SCORE_MISS        = 0.10   # pénalité score par usage raté

# Types valides
VAULT_TYPES = frozenset({
    "pattern", "error", "fix", "insight", "business", "code",
    "anti_pattern", "heuristic",  # aliases legacy
})


# ── Entrée Vault ──────────────────────────────────────────────────────────────

@dataclass
class VaultEntry:
    """
    Entrée structurée dans le Vault.

    Champs obligatoires à la création : type, content, source, confidence.
    """
    type:        str
    content:     str
    source:      str
    confidence:  float

    # Auto-générés
    id:          str       = field(default_factory=lambda: str(uuid.uuid4())[:8])
    usage_count: int       = 0
    last_used:   str|None  = None     # ISO 8601
    tags:        list[str] = field(default_factory=list)
    related_to:  list[str] = field(default_factory=list)
    valid:       bool      = True
    created_at:  float     = field(default_factory=time.time)
    expires_at:  float|None = None    # epoch — None = pas d'expiration

    def __post_init__(self):
        # Normalisation type
        if self.type not in VAULT_TYPES:
            self.type = "insight"
        # Clamp confidence
        self.confidence = max(0.0, min(1.0, float(self.confidence or 0.0)))
        # Normalise tags
        self.tags = [str(t).lower().strip() for t in self.tags if t]

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> str:
        """Hash court pour déduplication rapide par contenu."""
        norm = " ".join(self.content.lower().split())[:120]
        return hashlib.md5(norm.encode()).hexdigest()[:12]

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_active(self) -> bool:
        return self.valid and not self.is_expired()

    def relevance_score(self, query: str) -> float:
        """Score de pertinence pour une requête (keyword overlap × confidence)."""
        q_words = set(query.lower().split())
        t_words = set(f"{self.type} {' '.join(self.tags)} {self.content}".lower().split())
        hits = sum(1 for w in q_words if len(w) > 2 and w in t_words)
        base = hits / max(len(q_words), 1)
        recency_bonus = 0.05 if self.last_used else 0.0
        popularity_bonus = min(self.usage_count * 0.02, 0.20)
        return base * self.confidence + recency_bonus + popularity_bonus

    def boost(self, success: bool = True) -> None:
        """Ajuste confidence après usage (succès ou échec)."""
        if success:
            self.confidence = min(1.0, self.confidence + _SCORE_HIT)
        else:
            self.confidence = max(0.0, self.confidence - _SCORE_MISS)
            if self.confidence < _MIN_CONFIDENCE:
                self.valid = False
                log.info("vault_entry_invalidated", id=self.id, confidence=self.confidence)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt_snippet(self) -> str:
        """Format compact injectable dans un prompt."""
        tag_str = f" [{', '.join(self.tags[:3])}]" if self.tags else ""
        return f"[{self.type.upper()}]{tag_str} {self.content}"

    # ── Serialisation ─────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, d: dict) -> "VaultEntry":
        """Reconstruit depuis un dict JSON (ignore les clés inconnues)."""
        known = {
            "id", "type", "content", "source", "confidence",
            "usage_count", "last_used", "tags", "related_to",
            "valid", "created_at", "expires_at",
        }
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ── Vault Memory ──────────────────────────────────────────────────────────────

class VaultMemory:
    """
    Mémoire Vault — stockage structuré, fiable, exploitable.

    Usage :
        vm = VaultMemory()
        entry = vm.store(
            type="pattern",
            content="Toujours utiliser asyncio.wait_for() avec timeout",
            source="tests/test_async.py",
            confidence=0.85,
            tags=["python", "async", "timeout"],
        )
        results = vm.retrieve(query="async timeout", max_k=5)
        vm.feedback(entry.id, success=True)   # boost confidence
        vm.invalidate(entry.id)               # soft-delete
    """

    def __init__(self, storage_path: Path|str = _STORAGE_PATH):
        self._path        = Path(storage_path)
        self._entries:   dict[str, VaultEntry] = {}
        self._fps:       set[str] = set()          # fingerprints
        self._use_sqlite: bool = False
        self._use_pg:     bool = False
        self._pg_dsn:   str | None = None
        self._load()

    # ── API publique ──────────────────────────────────────────────────────────

    def store(
        self,
        type:       str,
        content:    str,
        source:     str,
        confidence: float,
        tags:       list[str]|None = None,
        related_to: list[str]|None = None,
        ttl_days:   int|None = None,
    ) -> VaultEntry|None:
        """
        Stocke une connaissance validée.
        Retourne None si rejetée (doublon, confidence trop faible).
        """
        content = content.strip()
        if not content:
            return None

        if confidence < _MIN_CONFIDENCE:
            log.debug("vault_rejected_low_confidence", confidence=confidence, src=source[:40])
            return None

        entry = VaultEntry(
            type=type,
            content=content,
            source=source,
            confidence=confidence,
            tags=tags or [],
            related_to=related_to or [],
            expires_at=time.time() + ttl_days * 86400 if ttl_days else None,
        )

        # Déduplication par fingerprint exact
        if entry.fingerprint in self._fps:
            log.debug("vault_duplicate_fp_skipped", fp=entry.fingerprint)
            return None

        # Déduplication Jaccard
        if self._is_jaccard_dup(content):
            log.debug("vault_duplicate_jaccard_skipped", content=content[:50])
            return None

        self._entries[entry.id] = entry
        self._fps.add(entry.fingerprint)

        # Rotation FIFO si overflow
        if len(self._entries) > _MAX_ENTRIES:
            self._evict_oldest(10)

        # SQLite direct insert
        if getattr(self, "_use_sqlite", False):
            try:
                from core import db as _db_mod
                _db_mod.execute(
                    """INSERT OR IGNORE INTO vault_entries
                       (id, type, content, source, confidence, usage_count, last_used,
                        tags, related_to, valid, created_at, expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        entry.id, entry.type, entry.content, entry.source,
                        entry.confidence, entry.usage_count, entry.last_used,
                        _db_mod.dumps(entry.tags), _db_mod.dumps(entry.related_to),
                        1 if entry.valid else 0,
                        entry.created_at, entry.expires_at,
                    )
                )
            except Exception:
                self._save_json()
        else:
            self._save()
        log.info("vault_stored", id=entry.id, type=type, tags=entry.tags)
        return entry

    def retrieve(
        self,
        query:   str,
        type_filter: str|None = None,
        tags_filter: list[str]|None = None,
        max_k:   int = 5,
        min_confidence: float = 0.35,
    ) -> list[VaultEntry]:
        """
        Récupère les entrées les plus pertinentes pour une requête.
        Filtre sur type/tags si fournis.
        """
        candidates = [
            e for e in self._entries.values()
            if e.is_active()
            and e.confidence >= min_confidence
            and (type_filter is None or e.type == type_filter)
            and (not tags_filter or any(t in e.tags for t in tags_filter))
        ]

        if query:
            candidates.sort(key=lambda e: e.relevance_score(query), reverse=True)
        else:
            candidates.sort(key=lambda e: e.confidence, reverse=True)

        return candidates[:max_k]

    def get_context_for_prompt(
        self,
        query:   str,
        max_k:   int = 3,
        type_filter: str|None = None,
        tags_filter: list[str]|None = None,
    ) -> str:
        """
        Retourne un bloc texte injectable dans un prompt.
        Marque automatiquement les entrées comme utilisées.
        """
        entries = self.retrieve(query, type_filter=type_filter,
                                tags_filter=tags_filter, max_k=max_k)
        if not entries:
            return ""

        lines = ["## Mémoire Vault (connaissances validées)"]
        for e in entries:
            lines.append(e.to_prompt_snippet())
            self._mark_used(e.id)

        return "\n".join(lines)

    def feedback(self, entry_id: str, success: bool = True) -> None:
        """
        Met à jour le score d'une entrée après usage.
        success=True → +0.05 confidence
        success=False → -0.10 confidence (invalide si < 0.30)
        """
        if entry_id in self._entries:
            self._entries[entry_id].boost(success)
            if getattr(self, "_use_sqlite", False):
                try:
                    from core import db as _db_mod
                    e = self._entries[entry_id]
                    _db_mod.execute(
                        "UPDATE vault_entries SET confidence=?, valid=? WHERE id=?",
                        (e.confidence, 1 if e.valid else 0, entry_id)
                    )
                    return
                except Exception:
                    pass
            self._save()

    def invalidate(self, entry_id: str) -> None:
        """Soft-delete : marque valid=False sans supprimer."""
        if entry_id in self._entries:
            self._entries[entry_id].valid = False
            self._save()
            log.info("vault_invalidated", id=entry_id)

    def get_by_id(self, entry_id: str) -> VaultEntry|None:
        return self._entries.get(entry_id)

    def get_by_type(self, type_: str, max_k: int = 10) -> list[VaultEntry]:
        return [
            e for e in sorted(
                self._entries.values(),
                key=lambda e: e.confidence, reverse=True,
            )
            if e.is_active() and e.type == type_
        ][:max_k]

    def get_by_tag(self, tag: str, max_k: int = 10) -> list[VaultEntry]:
        tag = tag.lower()
        return [
            e for e in sorted(
                self._entries.values(),
                key=lambda e: e.confidence, reverse=True,
            )
            if e.is_active() and tag in e.tags
        ][:max_k]

    def is_known(self, content: str) -> bool:
        """Retourne True si un contenu similaire est déjà dans le vault."""
        entry = VaultEntry(type="insight", content=content, source="", confidence=0.5)
        if entry.fingerprint in self._fps:
            return True
        return self._is_jaccard_dup(content)

    def prune_expired(self) -> int:
        """Supprime les entrées expirées ou invalidées. Retourne le count."""
        to_remove = [
            k for k, e in self._entries.items()
            if e.is_expired() or not e.valid
        ]
        for k in to_remove:
            fp = self._entries[k].fingerprint
            del self._entries[k]
            self._fps.discard(fp)
        if to_remove:
            if getattr(self, "_use_sqlite", False):
                try:
                    from core import db as _db_mod
                    now = time.time()
                    _db_mod.execute(
                        "DELETE FROM vault_entries WHERE valid=0 OR (expires_at IS NOT NULL AND expires_at < ?)",
                        (now,)
                    )
                except Exception:
                    self._save_json()
            else:
                self._save()
            log.info("vault_pruned", count=len(to_remove))
        return len(to_remove)

    def stats(self) -> dict:
        active = [e for e in self._entries.values() if e.is_active()]
        by_type: dict[str, int] = {}
        for e in active:
            by_type[e.type] = by_type.get(e.type, 0) + 1
        return {
            "total_active":    len(active),
            "total_entries":   len(self._entries),
            "by_type":         by_type,
            "avg_confidence":  round(
                sum(e.confidence for e in active) / max(len(active), 1), 3
            ),
            "total_uses":      sum(e.usage_count for e in active),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _mark_used(self, entry_id: str) -> None:
        if entry_id in self._entries:
            e = self._entries[entry_id]
            e.usage_count += 1
            e.last_used = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _is_jaccard_dup(self, content: str) -> bool:
        """Jaccard similarity sur bag-of-words."""
        words_new = set(content.lower().split())
        if len(words_new) < 4:
            return False
        for e in self._entries.values():
            if not e.is_active():
                continue
            words_e = set(e.content.lower().split())
            inter = words_new & words_e
            union = words_new | words_e
            if union and len(inter) / len(union) >= _DEDUP_THRESHOLD:
                return True
        return False

    def _evict_oldest(self, n: int) -> None:
        oldest = sorted(self._entries.values(), key=lambda e: e.created_at)
        for e in oldest[:n]:
            del self._entries[e.id]
            self._fps.discard(e.fingerprint)

    def _load(self) -> None:
        # Detect temp/test paths → skip DB, use JSON only
        import tempfile as _tf
        _tmp_dir = str(_tf.gettempdir()).replace("\\", "/").lower()
        _vpath   = str(self._path).replace("\\", "/").lower()
        _is_temp = _vpath.startswith(_tmp_dir) or "/temp/" in _vpath or "/tmp/" in _vpath

        # Try Postgres first (production)
        if not _is_temp:
            try:
                from config.settings import Settings
                dsn = Settings().database_url
                if dsn:
                    self._load_pg(dsn)
                    return
            except Exception as exc:
                log.debug("vault_pg_load_skipped", err=str(exc)[:80])

        # Try SQLite for real workspace paths
        if not _is_temp:
            try:
                from core.db import get_db, loads as db_loads
                from core import db as _db_mod
                db = get_db()
                if db is not None:
                    rows = _db_mod.fetchall(
                        "SELECT * FROM vault_entries WHERE valid=1 ORDER BY confidence DESC"
                    )
                    for row in rows:
                        try:
                            d = {
                                "id":          row["id"],
                                "type":        row["type"],
                                "content":     row["content"],
                                "source":      row["source"],
                                "confidence":  row["confidence"],
                                "usage_count": row["usage_count"] or 0,
                                "last_used":   row["last_used"],
                                "tags":        db_loads(row.get("tags"), []),
                                "related_to":  db_loads(row.get("related_to"), []),
                                "valid":       bool(row["valid"]),
                                "created_at":  row["created_at"],
                                "expires_at":  row["expires_at"],
                            }
                            entry = VaultEntry.from_dict(d)
                            self._entries[entry.id] = entry
                            self._fps.add(entry.fingerprint)
                        except Exception:
                            pass
                    self._use_sqlite = True
                    log.debug("vault_memory_loaded_sqlite", count=len(self._entries))
                    return
            except Exception as exc:
                log.warning("vault_sqlite_load_failed", err=str(exc))

        # Fallback JSON (always used for temp paths)
        self._use_sqlite = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text("utf-8"))
            for item in data.get("entries", []):
                try:
                    entry = VaultEntry.from_dict(item)
                    self._entries[entry.id] = entry
                    self._fps.add(entry.fingerprint)
                except Exception:
                    pass
            log.debug("vault_memory_loaded_json", count=len(self._entries))
        except Exception as exc:
            log.warning("vault_memory_load_failed", err=str(exc))

    # ── Postgres paths ──────────────────────────────────────────────────────

    def _load_pg(self, dsn: str) -> None:
        """Load vault entries from Postgres."""
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM vault_entries WHERE valid=1 ORDER BY confidence DESC"
        )
        for row in cur.fetchall():
            try:
                d = {
                    "id":          row["id"],
                    "type":        row["type"],
                    "content":     row["content"],
                    "source":      row["source"],
                    "confidence":  row["confidence"],
                    "usage_count": row["usage_count"] or 0,
                    "last_used":   row["last_used"],
                    "tags":        json.loads(row["tags"]) if row.get("tags") else [],
                    "related_to":  json.loads(row["related_to"]) if row.get("related_to") else [],
                    "valid":       bool(row["valid"]),
                    "created_at":  row["created_at"],
                    "expires_at":  row["expires_at"],
                }
                entry = VaultEntry.from_dict(d)
                self._entries[entry.id] = entry
                self._fps.add(entry.fingerprint)
            except Exception:
                pass
        cur.close()
        conn.close()
        self._use_pg = True
        self._pg_dsn = dsn
        log.debug("vault_memory_loaded_pg", count=len(self._entries))

    def _save_pg(self) -> None:
        """Persist vault entries to Postgres."""
        try:
            import psycopg2
            conn = psycopg2.connect(self._pg_dsn)
            conn.autocommit = True
            cur = conn.cursor()
            for entry in self._entries.values():
                cur.execute(
                    """INSERT INTO vault_entries
                       (id, type, content, source, confidence, usage_count, last_used,
                        tags, related_to, valid, created_at, expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET
                        type=EXCLUDED.type, content=EXCLUDED.content,
                        source=EXCLUDED.source, confidence=EXCLUDED.confidence,
                        usage_count=EXCLUDED.usage_count, last_used=EXCLUDED.last_used,
                        tags=EXCLUDED.tags, related_to=EXCLUDED.related_to,
                        valid=EXCLUDED.valid, expires_at=EXCLUDED.expires_at""",
                    (
                        entry.id, entry.type, entry.content, entry.source,
                        entry.confidence, entry.usage_count, entry.last_used,
                        json.dumps(entry.tags), json.dumps(entry.related_to),
                        1 if entry.valid else 0,
                        entry.created_at, entry.expires_at,
                    )
                )
            cur.close()
            conn.close()
            log.debug("vault_memory_saved_pg", count=len(self._entries))
        except Exception as exc:
            log.warning("vault_pg_save_failed", err=str(exc)[:80])
            self._save_sqlite()   # fallback

    # ── Save dispatcher ──────────────────────────────────────────────────────

    def _save(self) -> None:
        if getattr(self, "_use_pg", False):
            self._save_pg()
        elif getattr(self, "_use_sqlite", False):
            self._save_sqlite()
        else:
            self._save_json()

    def _save_sqlite(self) -> None:
        try:
            from core import db as _db_mod
            for entry in self._entries.values():
                _db_mod.execute(
                    """INSERT OR REPLACE INTO vault_entries
                       (id, type, content, source, confidence, usage_count, last_used,
                        tags, related_to, valid, created_at, expires_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        entry.id, entry.type, entry.content, entry.source,
                        entry.confidence, entry.usage_count, entry.last_used,
                        _db_mod.dumps(entry.tags), _db_mod.dumps(entry.related_to),
                        1 if entry.valid else 0,
                        entry.created_at, entry.expires_at,
                    )
                )
        except Exception as exc:
            log.warning("vault_sqlite_save_failed", err=str(exc))
            self._save_json()

    def _save_json(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version":  2,
                "saved_at": time.time(),
                "entries":  [e.to_dict() for e in self._entries.values()],
            }
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        except Exception as exc:
            log.warning("vault_memory_save_failed", err=str(exc))


# ── Singleton + Layer API ─────────────────────────────────────────────────────

_vault_instance: VaultMemory|None = None
_LAYER_JSONL = Path("workspace/vault_layers.jsonl")
_MAX_LAYER_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def get_vault_memory() -> VaultMemory:
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = VaultMemory()
    return _vault_instance


# Layer storage — in-memory dict per layer loaded from JSONL
_layer_data: dict[str, list[dict]] = {"short_term": [], "working": [], "long_term": []}
_layer_loaded: bool = False


def _load_layer_data() -> None:
    global _layer_loaded
    if _layer_loaded:
        return
    _layer_loaded = True
    if not _LAYER_JSONL.exists():
        return
    try:
        for line in _LAYER_JSONL.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                layer = d.get("layer", "working")
                if layer in _layer_data:
                    _layer_data[layer].append(d)
            except Exception:
                pass
    except Exception:
        pass


def _persist_layers() -> None:
    try:
        _LAYER_JSONL.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for layer_entries in _layer_data.values():
            for e in layer_entries:
                lines.append(json.dumps(e, ensure_ascii=False))
        content = "\n".join(lines)
        # Cap file at 10MB
        if len(content.encode("utf-8")) > _MAX_LAYER_FILE_BYTES:
            # Trim oldest entries per layer until under limit
            for layer in list(_layer_data.keys()):
                if len(_layer_data[layer]) > 20:
                    _layer_data[layer] = _layer_data[layer][len(_layer_data[layer])//2:]
            lines = []
            for layer_entries in _layer_data.values():
                for e in layer_entries:
                    lines.append(json.dumps(e, ensure_ascii=False))
            content = "\n".join(lines)
        _LAYER_JSONL.write_text(content, "utf-8")
    except Exception as exc:
        log.warning("vault_layer_persist_failed", err=str(exc))


# Extend VaultMemory with layer methods
def _vm_get_instance(cls) -> "VaultMemory":
    return get_vault_memory()


def _vm_store_entry(self: VaultMemory, entry: "MemoryEntry", layer: str = "working") -> None:
    """Stocke une MemoryEntry dans le layer spécifié. Éviction FIFO si cap dépassé."""
    _load_layer_data()
    cfg = LAYER_CONFIG.get(layer, LAYER_CONFIG["working"])
    entry.layer = layer
    d = entry.to_dict()
    _layer_data[layer].append(d)
    # Auto-éviction FIFO si > max_items
    max_items = cfg["max_items"]
    if len(_layer_data[layer]) > max_items:
        _layer_data[layer] = _layer_data[layer][-max_items:]
    _persist_layers()


def _vm_search_entries(
    self: VaultMemory,
    query: str,
    layer: str | None = None,
    top_k: int = 5,
) -> list["MemoryEntry"]:
    """Recherche keyword dans les layers. Retourne les entrées les plus pertinentes."""
    _load_layer_data()
    q_words = set(query.lower().split())
    candidates: list[dict] = []
    layers_to_search = [layer] if layer else list(_layer_data.keys())
    for ly in layers_to_search:
        candidates.extend(_layer_data.get(ly, []))

    if not q_words:
        results = candidates[:top_k]
    else:
        def _score(d: dict) -> int:
            text = f"{d.get('context','')} {d.get('decision','')} {' '.join(d.get('tags',[]))}".lower()
            return sum(1 for w in q_words if w in text)
        results = sorted(candidates, key=_score, reverse=True)[:top_k]

    out = []
    for d in results:
        try:
            out.append(MemoryEntry.from_dict(d))
        except Exception:
            pass
    return out


def _vm_cleanup_expired(self: VaultMemory) -> int:
    """Supprime les entrées dont l'âge dépasse le TTL de leur layer."""
    _load_layer_data()
    removed = 0
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    import datetime
    now_dt = datetime.datetime.utcnow()

    for layer, entries in _layer_data.items():
        cfg = LAYER_CONFIG.get(layer, LAYER_CONFIG["working"])
        ttl_hours = cfg["ttl_hours"]
        cutoff = now_dt - datetime.timedelta(hours=ttl_hours)
        before = len(entries)
        kept = []
        for e in entries:
            ts = e.get("timestamp", "")
            try:
                entry_dt = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
                if entry_dt >= cutoff:
                    kept.append(e)
            except Exception:
                kept.append(e)  # garde si timestamp invalide
        _layer_data[layer] = kept
        removed += before - len(kept)

    if removed:
        _persist_layers()
    return removed


def _vm_summarize_layer(self: VaultMemory, layer: str) -> str:
    """Si layer > 80% capacité, résume la moitié la plus ancienne en une entrée compacte."""
    _load_layer_data()
    cfg = LAYER_CONFIG.get(layer, LAYER_CONFIG["working"])
    entries = _layer_data.get(layer, [])
    max_items = cfg["max_items"]
    if len(entries) < int(max_items * 0.8):
        return f"Layer '{layer}': {len(entries)}/{max_items} entries — no summary needed."

    half = len(entries) // 2
    old_entries = entries[:half]
    _layer_data[layer] = entries[half:]

    # Compact summary entry
    contexts = [e.get("context", "")[:50] for e in old_entries[:10]]
    summary_text = f"[auto-summary {len(old_entries)} entries] " + "; ".join(contexts)
    import uuid as _uuid
    compact = MemoryEntry(
        id=str(_uuid.uuid4())[:12],
        layer=layer,
        context=summary_text[:200],
        decision="auto-summarized",
        result="PARTIAL",
        score=0.5,
        tags=["auto-summary"],
        mission_id="system",
    )
    _layer_data[layer].insert(0, compact.to_dict())
    _persist_layers()
    return f"Layer '{layer}': summarized {len(old_entries)} old entries into 1 compact entry."


def _vm_get_success_patterns(self: VaultMemory, top_k: int = 10) -> list["MemoryEntry"]:
    _load_layer_data()
    all_entries = []
    for entries in _layer_data.values():
        all_entries.extend(entries)
    out = [MemoryEntry.from_dict(e) for e in all_entries if e.get("score", 0) >= 0.7]
    return sorted(out, key=lambda x: x.score, reverse=True)[:top_k]


def _vm_get_failure_patterns(self: VaultMemory, top_k: int = 10) -> list["MemoryEntry"]:
    _load_layer_data()
    all_entries = []
    for entries in _layer_data.values():
        all_entries.extend(entries)
    return [MemoryEntry.from_dict(e) for e in all_entries if e.get("score", 0) < 0.3][:top_k]


# Original store method saved for dispatch
_vm_store_original = VaultMemory.store


def _vm_store_dispatch(self: VaultMemory, type_or_entry=None, layer: str = "working", **kwargs):
    """
    Dispatch store() :
    - store(entry, layer='working') → store_entry (V1 layer API)
    - store(type=..., content=..., ...) → original VaultEntry store
    """
    # Import ici pour éviter référence circulaire au moment du chargement
    from memory.vault_memory import MemoryEntry as _ME
    if isinstance(type_or_entry, _ME):
        _vm_store_entry(self, type_or_entry, layer)
        return None
    # Forward to original store
    if type_or_entry is not None:
        return _vm_store_original(self, type_or_entry, **kwargs)
    return _vm_store_original(self, **kwargs)


def _vm_search_dispatch(self: VaultMemory, query: str, layer: str | None = None, top_k: int = 5) -> list:
    """search() — keyword search dans les layers."""
    return _vm_search_entries(self, query, layer=layer, top_k=top_k)


# Monkey-patch layer methods onto VaultMemory
VaultMemory.get_instance            = classmethod(lambda cls: get_vault_memory())
VaultMemory.store                   = _vm_store_dispatch
VaultMemory.search                  = _vm_search_dispatch
VaultMemory.store_entry             = _vm_store_entry
VaultMemory.search_entries          = _vm_search_entries
VaultMemory.cleanup_expired         = _vm_cleanup_expired
VaultMemory.summarize_layer         = _vm_summarize_layer
VaultMemory.get_success_patterns_layer = _vm_get_success_patterns
VaultMemory.get_failure_patterns_layer = _vm_get_failure_patterns


# ── Layer system V1 ──────────────────────────────────────────────────────────

LAYER_CONFIG: dict[str, dict] = {
    "short_term": {"max_items": 50,   "ttl_hours": 4},
    "working":    {"max_items": 200,  "ttl_hours": 48},
    "long_term":  {"max_items": 1000, "ttl_hours": 720},  # 30 jours
}


# ── MemoryEntry (Phase 5 spec) ────────────────────────────────────────────────
# Interface simplifiée pour les entrées de mission.

_MISSION_JSONL = Path("workspace/vault_memory.jsonl")


@dataclass
class MemoryEntry:
    """Entrée de mémoire de mission — interface V1 standardisée."""
    context:    str
    decision:   str
    result:     str        # SUCCESS / FAILED / PARTIAL
    score:      float      # 0.0-1.0
    tags:       list[str]  = field(default_factory=list)
    timestamp:  str        = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    mission_id: str        = ""
    id:         str        = field(default_factory=lambda: str(uuid.uuid4())[:12])
    layer:      str        = "working"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def _load_mission_entries() -> list[MemoryEntry]:
    """Charge toutes les MemoryEntry depuis vault_memory.jsonl."""
    if not _MISSION_JSONL.exists():
        return []
    entries: list[MemoryEntry] = []
    try:
        for line in _MISSION_JSONL.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(MemoryEntry.from_dict(json.loads(line)))
            except Exception:
                pass
    except Exception:
        pass
    return entries


def store_memory_entry(entry: MemoryEntry) -> None:
    """Persiste une MemoryEntry dans workspace/vault_memory.jsonl (append)."""
    try:
        _MISSION_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with _MISSION_JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning("vault_jsonl_write_failed", err=str(exc))


def search_memory(query: str, top_k: int = 5) -> list[MemoryEntry]:
    """Recherche keyword simple dans les MemoryEntry (pas de vecteur)."""
    q_words = set(query.lower().split())
    entries = _load_mission_entries()
    if not q_words:
        return entries[:top_k]

    def _score(e: MemoryEntry) -> int:
        text = f"{e.context} {e.decision} {' '.join(e.tags)}".lower()
        return sum(1 for w in q_words if w in text)

    return sorted(entries, key=_score, reverse=True)[:top_k]


def get_patterns_by_tag(tag: str) -> list[MemoryEntry]:
    """Récupère les MemoryEntry correspondant à un tag."""
    tag = tag.lower()
    return [e for e in _load_mission_entries() if tag in [t.lower() for t in e.tags]]


def get_success_patterns() -> list[MemoryEntry]:
    """Retourne les MemoryEntry avec score >= 0.7."""
    return [e for e in _load_mission_entries() if e.score >= 0.7]


def get_failure_patterns() -> list[MemoryEntry]:
    """Retourne les MemoryEntry avec score < 0.3."""
    return [e for e in _load_mission_entries() if e.score < 0.3]
