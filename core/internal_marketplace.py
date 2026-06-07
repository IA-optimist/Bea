"""
BEA MAX — Internal Skill/Module Marketplace
==================================================
Local catalog of installable modules (agents, skills, connectors, MCP).
No external service dependency — self-contained.

Extends the existing modules_v3 catalog with:
  - Versioning
  - Ratings (from reputation + usage stats)
  - Dependency declarations
  - Install/uninstall tracking
  - Featured/recommended based on usage
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()

_CATALOG_PATH = os.environ.get("MARKETPLACE_CATALOG_PATH", "data/marketplace_catalog.json")
_singleton: Optional["InternalMarketplace"] = None
_lock = threading.Lock()


def get_marketplace() -> "InternalMarketplace":
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                _singleton = InternalMarketplace()
    return _singleton


@dataclass
class CatalogEntry:
    """A module available in the internal marketplace."""
    id: str = ""
    name: str = ""
    type: str = ""  # agent, skill, connector, mcp
    version: str = "1.0.0"
    description: str = ""
    author: str = "bea"
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    required_secrets: List[str] = field(default_factory=list)
    install_count: int = 0
    rating: float = 0.0  # 0.0-5.0
    featured: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "type": self.type,
            "version": self.version, "description": self.description,
            "author": self.author, "category": self.category,
            "tags": self.tags, "dependencies": self.dependencies,
            "required_secrets": self.required_secrets,
            "install_count": self.install_count,
            "rating": round(self.rating, 1), "featured": self.featured,
        }


class InternalMarketplace:
    """Self-contained local marketplace for BeaMax modules."""

    def __init__(self, catalog_path: str = _CATALOG_PATH):
        self._lock = threading.RLock()
        self._entries: Dict[str, CatalogEntry] = {}
        self._path = Path(catalog_path)
        self._load()

    # ── CRUD ──

    def register(self, entry: CatalogEntry) -> CatalogEntry:
        with self._lock:
            self._entries[entry.id] = entry
            self._save()
        return entry

    def get(self, entry_id: str) -> Optional[CatalogEntry]:
        return self._entries.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._save()
                return True
        return False

    # ── Search ──

    def search(
        self,
        query: str = "",
        type: str = "",
        category: str = "",
        featured_only: bool = False,
    ) -> List[CatalogEntry]:
        results = []
        q = query.lower()
        for e in self._entries.values():
            if type and e.type != type:
                continue
            if category and e.category != category:
                continue
            if featured_only and not e.featured:
                continue
            if q and q not in e.name.lower() and q not in e.description.lower() and not any(q in t for t in e.tags):
                continue
            results.append(e)
        return sorted(results, key=lambda e: e.rating, reverse=True)

    def list_all(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in sorted(self._entries.values(), key=lambda e: e.install_count, reverse=True)]

    def get_recommended(self, limit: int = 5) -> List[CatalogEntry]:
        """Return top-rated, most-installed modules."""
        return sorted(
            self._entries.values(),
            key=lambda e: (e.featured, e.rating, e.install_count),
            reverse=True,
        )[:limit]

    # ── Install tracking ──

    def record_install(self, entry_id: str) -> None:
        with self._lock:
            e = self._entries.get(entry_id)
            if e:
                e.install_count += 1
                e.updated_at = time.time()
                self._save()

    def update_rating(self, entry_id: str, score: float) -> None:
        """Update rating with exponential moving average."""
        with self._lock:
            e = self._entries.get(entry_id)
            if e:
                if e.rating == 0:
                    e.rating = score
                else:
                    e.rating = e.rating * 0.7 + score * 0.3
                e.updated_at = time.time()
                self._save()

    # ── Dependency check ──

    def check_dependencies(self, entry_id: str) -> Dict[str, Any]:
        """Check if all dependencies of an entry are available."""
        entry = self._entries.get(entry_id)
        if not entry:
            return {"ok": False, "reason": "Entry not found"}
        missing = [d for d in entry.dependencies if d not in self._entries]
        secrets_needed = entry.required_secrets
        return {
            "ok": len(missing) == 0,
            "missing_modules": missing,
            "required_secrets": secrets_needed,
        }

    # ── Stats ──

    def stats(self) -> Dict[str, Any]:
        by_type = {}
        for e in self._entries.values():
            by_type[e.type] = by_type.get(e.type, 0) + 1
        return {
            "total": len(self._entries),
            "by_type": by_type,
            "featured": sum(1 for e in self._entries.values() if e.featured),
            "total_installs": sum(e.install_count for e in self._entries.values()),
        }

    # ── Persistence ──

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {eid: {
                **e.to_dict(), "created_at": e.created_at, "updated_at": e.updated_at,
            } for eid, e in self._entries.items()}
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.warning("marketplace_save_failed", err=str(e))

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text())
            for eid, vals in data.items():
                self._entries[eid] = CatalogEntry(
                    id=eid, name=vals.get("name", ""), type=vals.get("type", ""),
                    version=vals.get("version", "1.0.0"), description=vals.get("description", ""),
                    author=vals.get("author", ""), category=vals.get("category", ""),
                    tags=vals.get("tags", []), dependencies=vals.get("dependencies", []),
                    required_secrets=vals.get("required_secrets", []),
                    install_count=vals.get("install_count", 0), rating=vals.get("rating", 0),
                    featured=vals.get("featured", False),
                    created_at=vals.get("created_at", 0), updated_at=vals.get("updated_at", 0),
                )
        except Exception as e:
            log.warning("marketplace_load_failed", err=str(e))
