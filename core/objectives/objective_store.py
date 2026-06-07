"""
Objective Engine — Persistance JSON locale + Qdrant secondaire.
- Primaire  : workspace/objectives/objectives.json (atomique)
- Secondaire: Qdrant collection "bea_objectives" (fail-open si down)
- Toute erreur est loguée et ignorée (fail-open total)
"""
from __future__ import annotations

import json
import structlog
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from core.objectives.objective_models import Objective, ObjectiveStatus

logger = structlog.get_logger("bea.objective_store")
log = logger  # M3 emitter alias

# ── Chemins ────────────────────────────────────────────────────────────────────

def _get_store_path() -> Path:
    """Résout le chemin du store. Configurable via BEA_WORKSPACE."""
    workspace = os.environ.get(
        "BEA_WORKSPACE",
        str(Path(__file__).parents[2] / "workspace"),
    )
    path = Path(workspace) / "objectives"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as _exc:
        log.warning("swallowed_exception", action="objective_store_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
    return path / "objectives.json"


# ── Qdrant (LEGACY - désactivé, migration pgvector terminée) ───────────────────

# _QDRANT_AVAILABLE = False
# _QDRANT_HEADERS: dict = {}
# try:
#     import requests as _requests
#     _QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
#     _QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
#     _QDRANT_URL  = f"http://{_QDRANT_HOST}:{_QDRANT_PORT}"
#     _QDRANT_COLLECTION = "bea_objectives"
#     _QDRANT_DIM = 768
#     _QDRANT_API_KEY=os.environ.get("QDRANT_API_KEY", "")
#     if _QDRANT_API_KEY:
#         _QDRANT_HEADERS = {"api-key": _QDRANT_API_KEY}
#     _QDRANT_AVAILABLE = True
# except ImportError:
#     pass


# def _make_vector(text: str, dim: int = 768) -> List[float]:
#     """Vecteur pseudo-aléatoire déterministe basé sur le hash du texte."""
#     seed = int(hashlib.md5(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:8], 16)
#     rng = random.Random(seed)
#     vec = [rng.gauss(0, 1) for _ in range(dim)]
#     norm = sum(x * x for x in vec) ** 0.5
#     if norm == 0:
#         return [0.0] * dim
#     return [x / norm for x in vec]


# def _qdrant_ensure_collection() -> bool:
#     """Crée la collection Qdrant si elle n'existe pas. Fail-open."""
#     if not _QDRANT_AVAILABLE:
#         return False
#     try:
#         r = _requests.get(
#             f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}",
#             headers=_QDRANT_HEADERS,
#             timeout=3,
#         )
#         if r.status_code == 200:
#             return True
#         # Créer la collection
#         _requests.put(
#             f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}",
#             headers=_QDRANT_HEADERS,
#             json={
#                 "vectors": {
#                     "size": _QDRANT_DIM,
#                     "distance": "Cosine",
#                 }
#             },
#             timeout=3,
#         )
#         return True
#     except Exception as e:
#         logger.debug(f"[OBJECTIVE_STORE] qdrant collection check failed: {e}")
#         return False


# def _qdrant_upsert(obj: Objective) -> bool:
#     """Upsert un objectif dans Qdrant. Fail-open."""
#     if not _QDRANT_AVAILABLE:
#         return False
#     try:
#         _qdrant_ensure_collection()
#         text = f"{obj.title} {obj.description} {obj.category}"
#         vector = _make_vector(text)
#         # Convertir objective_id en int pour Qdrant (utiliser hash)
#         point_id = abs(hash(obj.objective_id)) % (2**31)
#         payload = {
#             "objective_id": obj.objective_id,
#             "title":         obj.title,
#             "status":        obj.status,
#             "category":      obj.category,
#             "priority_score": obj.priority_score,
#             "updated_at":    obj.updated_at,
#         }
#         _requests.put(
#             f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}/points",
#             headers=_QDRANT_HEADERS,
#             json={"points": [{"id": point_id, "vector": vector, "payload": payload}]},
#             timeout=3,
#         )
#         return True
#     except Exception as e:
#         logger.debug(f"[OBJECTIVE_STORE] qdrant upsert failed: {e}")
#         return False


# def _qdrant_search(query: str, top_k: int = 5) -> List[dict]:
#     """Recherche des objectifs similaires dans Qdrant. Fail-open."""
#     if not _QDRANT_AVAILABLE:
#         return []
#     try:
#         _qdrant_ensure_collection()
#         vector = _make_vector(query)
#         r = _requests.post(
#             f"{_QDRANT_URL}/collections/{_QDRANT_COLLECTION}/points/search",
#             headers=_QDRANT_HEADERS,
#             json={"vector": vector, "limit": top_k, "with_payload": True},
#             timeout=3,
#         )
#         if r.status_code == 200:
#             return [hit.get("payload", {}) for hit in r.json().get("result", [])]
#         return []
#     except Exception as e:
#         logger.debug(f"[OBJECTIVE_STORE] qdrant search failed: {e}")
#         return []


# ── Persistance JSON locale ────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> bool:
    """Écriture atomique via fichier temporaire + os.replace."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return True
    except Exception as e:
        logger.warning(f"[OBJECTIVE_STORE] atomic write failed: {e}")
        return False


# ── ObjectiveStore ─────────────────────────────────────────────────────────────

class ObjectiveStore:
    """
    Store d'objectifs avec persistance JSON locale + Qdrant secondaire.
    Thread-safety basique (pas de multiprocessus, single-process assumption).
    Fail-open : toute erreur est loguée et ignorée.
    """

    def __init__(self, store_path: Optional[Path] = None):
        self._path: Path = store_path or _get_store_path()
        self._cache: Dict[str, Objective] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text("utf-8"))
                for oid, obj_dict in raw.items():
                    try:
                        self._cache[oid] = Objective.from_dict(obj_dict)
                    except Exception as e:
                        logger.warning(f"[OBJECTIVE_STORE] skip corrupt entry {oid}: {e}")
                logger.debug(f"[OBJECTIVE_STORE] loaded {len(self._cache)} objectives")
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] load failed: {e}")

    def _save(self) -> bool:
        try:
            data = {oid: obj.to_dict() for oid, obj in self._cache.items()}
            return _atomic_write(self._path, data)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] save failed: {e}")
            return False

    # ── CRUD ─────────────────────────────────────────────────────────────

    def save(self, obj: Objective) -> bool:
        """Sauvegarde un objectif (JSON primaire + Qdrant secondaire)."""
        try:
            self._load()
            obj.updated_at = time.time()
            self._cache[obj.objective_id] = obj
            ok = self._save()
            # Qdrant secondaire — LEGACY désactivé
            # _qdrant_upsert(obj)
            if ok:
                logger.info(
                    json.dumps({
                        "event": "objective_saved",
                        "objective_id": obj.objective_id,
                        "status": obj.status,
                        "score": round(obj.priority_score, 3),
                        "ts": time.time(),
                    })
                )
            return ok
        except Exception as e:
            logger.error(f"[OBJECTIVE_STORE] save error: {e}")
            return False

    def get(self, objective_id: str) -> Optional[Objective]:
        """Retourne un objectif par ID."""
        try:
            self._load()
            return self._cache.get(objective_id)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] get error: {e}")
            return None

    def get_all(self, include_archived: bool = False) -> List[Objective]:
        """Retourne tous les objectifs."""
        try:
            self._load()
            result = list(self._cache.values())
            if not include_archived:
                result = [o for o in result if not o.archived]
            return sorted(result, key=lambda o: o.priority_score, reverse=True)
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] get_all error: {e}")
            return []

    def get_active(self) -> List[Objective]:
        """Retourne les objectifs actifs (NEW, ACTIVE, WAITING_APPROVAL)."""
        try:
            self._load()
            return [
                o for o in self._cache.values()
                if o.status in ObjectiveStatus.ACTIVE_STATES and not o.archived
            ]
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] get_active error: {e}")
            return []

    def delete(self, objective_id: str) -> bool:
        """Supprime un objectif (hard delete — utiliser archive() de préférence)."""
        try:
            self._load()
            if objective_id in self._cache:
                del self._cache[objective_id]
                return self._save()
            return False
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] delete error: {e}")
            return False

    def search_similar(self, query: str, top_k: int = 5) -> List[dict]:
        """
        Recherche des objectifs similaires.
        Primaire : Qdrant. Fallback : recherche textuelle locale.
        """
        try:
            # Tenter Qdrant d'abord — LEGACY désactivé
            # qdrant_results = _qdrant_search(query, top_k)
            # if qdrant_results:
            #     return qdrant_results
            # Fallback : recherche locale par mots-clés
            self._load()
            query_words = set(query.lower().split())
            scored = []
            for obj in self._cache.values():
                text = f"{obj.title} {obj.description}".lower()
                text_words = set(text.split())
                overlap = len(query_words & text_words)
                if overlap > 0:
                    scored.append((overlap, obj.to_dict()))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for _, d in scored[:top_k]]
        except Exception as e:
            logger.warning(f"[OBJECTIVE_STORE] search_similar error: {e}")
            return []

    def count(self) -> int:
        try:
            self._load()
            return len(self._cache)
        except Exception:
            return 0


# ── Singleton ──────────────────────────────────────────────────────────────────

_store: Optional[ObjectiveStore] = None


def get_objective_store(store_path: Optional[Path] = None) -> ObjectiveStore:
    global _store
    if _store is None:
        _store = ObjectiveStore(store_path)
    return _store


def reset_store() -> None:
    """Reset le singleton (pour les tests)."""
    global _store
    _store = None
