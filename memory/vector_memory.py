"""
BEA MAX — VectorMemory
Mémoire contextuelle locale via embeddings numpy + sentence-transformers.

Architecture :
    - Embeddings : sentence-transformers/all-MiniLM-L6-v2 (léger, ~22M params)
    - Similarité : cosine similarity numpy (pas de FAISS requis)
    - Persistance : workspace/vector_store.json (textes + vecteurs en base64)
    - Fallback   : si sentence-transformers absent → similarité par mots-clés TF-IDF

Cas d'usage :
    - Retrouver des patchs similaires passés
    - Retrouver des contextes de findings similaires
    - Suggestions basées sur des cas précédents

Interface :
    vm = VectorMemory(settings)
    doc_id = vm.add(text, metadata)
    results = vm.search(query, top_k=3)
    # → [{"id": ..., "text": ..., "score": 0.87, "metadata": {...}}, ...]
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger()

_MODEL_NAME   = "all-MiniLM-L6-v2"
_MAX_DOCS     = 2000
_DEFAULT_TOPK = 5


class VectorMemory:
    """
    Mémoire vectorielle locale.
    Utilise sentence-transformers si disponible, sinon TF-IDF simplifié.
    """

    VECTOR_DIM = 768  # Default embedding dimension

    def __init__(self, settings):
        self.s         = settings
        self._path     = self._resolve_path()
        self._docs:    list[dict] = []     # {"id", "text", "metadata", "vec_b64"}
        self._encoder  = None              # lazy-loaded
        self._fallback = False             # True si sentence-transformers absent
        self._load()

    # ── Persistance ───────────────────────────────────────────

    def _resolve_path(self) -> Path:
        base = Path(getattr(self.s, "workspace_dir", "/app/workspace"))
        base.mkdir(parents=True, exist_ok=True)
        return base / "vector_store.json"

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._docs = json.loads(self._path.read_text("utf-8"))
                log.debug("vector_memory_loaded", count=len(self._docs))
            except Exception as e:
                log.warning("vector_memory_load_error", err=str(e))
                self._docs = []

    def _save(self) -> None:
        if len(self._docs) > _MAX_DOCS:
            self._docs = self._docs[-_MAX_DOCS:]
        try:
            self._path.write_text(
                json.dumps(self._docs, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            log.error("vector_memory_save_error", err=str(e))

    # ── Encodeur ──────────────────────────────────────────────

    def _get_embedding_provider(self) -> str:
        """Return the configured embedding provider ('huggingface' or 'local')."""
        try:
            from config.settings import get_settings
            return getattr(get_settings(), "embedding_provider", "local")
        except Exception:
            import os
            return os.environ.get("EMBEDDING_PROVIDER", "local")

    def _encode_hf(self, text: str) -> list[float] | None:
        """Encode text using HuggingFace Inference API (sentence-transformers/all-MiniLM-L6-v2)."""
        import os
        try:
            from config.settings import get_settings
            hf_key = getattr(get_settings(), "huggingface_api_key", "") or os.getenv("HUGGINGFACE_API_KEY", "")
        except Exception:
            hf_key = os.getenv("HUGGINGFACE_API_KEY", "")

        if not hf_key:
            log.warning("vector_memory_hf_no_key", fallback="tfidf")
            return None

        try:
            import httpx
            hf_url = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
            # httpx sync call wrapped in thread executor — called from sync context
            resp = httpx.post(
                hf_url,
                headers={"Authorization": f"Bearer {hf_key}"},
                json={"inputs": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            # API returns list of floats (single sentence → flat list)
            if isinstance(data, list) and data and isinstance(data[0], list):
                vec = data[0]
            elif isinstance(data, list) and data and isinstance(data[0], float):
                vec = data
            else:
                log.warning("vector_memory_hf_unexpected_shape", type=type(data).__name__)
                return None
            log.info("vector_memory_hf_encoded", dims=len(vec))
            return vec
        except Exception as e:
            log.warning("vector_memory_hf_encode_error", err=str(e)[:80])
            return None

    def _get_encoder(self):
        """Charge sentence-transformers en lazy. Fallback TF-IDF si absent."""
        if self._encoder is not None:
            return self._encoder
        try:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(_MODEL_NAME)
            log.info("vector_memory_encoder_loaded", model=_MODEL_NAME)
        except Exception as e:
            log.warning("vector_memory_no_transformer",
                        err=str(e)[:80], fallback="tfidf")
            self._fallback = True
        return self._encoder

    def _encode(self, text: str) -> list[float] | None:
        """Encode un texte en vecteur. Retourne None si encodeur absent.

        If embedding_provider == 'huggingface', uses HF Inference API.
        Otherwise uses sentence-transformers locally (or TF-IDF fallback).
        Never raises — returns None on any failure.
        """
        try:
            provider = self._get_embedding_provider()
            if provider == "huggingface":
                result = self._encode_hf(text)
                if result is not None:
                    return result
                # Fallback to local if HF failed
                log.debug("vector_memory_hf_encode_fallback_local")
        except Exception as e:
            log.warning("vector_memory_provider_check_error", err=str(e)[:80])

        enc = self._get_encoder()
        if self._fallback or enc is None:
            return None
        try:
            vec = enc.encode(text, normalize_embeddings=True)
            vec_list = vec.tolist()
            # Pad to 768 if using 384-dim model
            if len(vec_list) < self.VECTOR_DIM:
                vec_list = vec_list + [0.0] * (self.VECTOR_DIM - len(vec_list))
            elif len(vec_list) > self.VECTOR_DIM:
                vec_list = vec_list[:self.VECTOR_DIM]
            return vec_list
        except Exception as e:
            log.warning("vector_memory_encode_error", err=str(e)[:80])
            return None

    @staticmethod
    def _vec_to_b64(vec: list[float]) -> str:
        import numpy as np
        import struct
        arr   = np.array(vec, dtype=np.float32)
        raw   = struct.pack(f"{len(arr)}f", *arr)
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _b64_to_vec(b64: str) -> list[float]:
        import struct
        raw  = base64.b64decode(b64)
        n    = len(raw) // 4
        return list(struct.unpack(f"{n}f", raw))

    # ── Similarité ────────────────────────────────────────────

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        import numpy as np
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        denom = (np.linalg.norm(va) * np.linalg.norm(vb))
        if denom == 0:
            return 0.0
        return float(np.dot(va, vb) / denom)

    @staticmethod
    def _tfidf_sim(query: str, text: str) -> float:
        """Similarité par chevauchement de tokens (fallback sans vecteurs)."""
        q_tokens = set(query.lower().split())
        t_tokens = set(text.lower().split())
        if not q_tokens or not t_tokens:
            return 0.0
        inter = q_tokens & t_tokens
        return len(inter) / max(len(q_tokens), len(t_tokens))

    # ── API publique ──────────────────────────────────────────

    def add(self, text: str, metadata: dict | None = None) -> str:
        """
        Ajoute un document à la mémoire vectorielle.
        Retourne l'ID du document.

        Si le même texte (hash) est déjà présent, retourne l'ID existant.
        """
        if not text or not text.strip():
            return ""

        # Déduplication par hash du texte
        doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        for doc in self._docs:
            if doc.get("hash") == doc_hash:
                return doc["id"]

        vec     = self._encode(text)
        vec_b64 = self._vec_to_b64(vec) if vec else ""

        doc_id = f"vm_{doc_hash}"
        self._docs.append({
            "id":       doc_id,
            "text":     text[:2000],        # limiter la taille stockée
            "hash":     doc_hash,
            "metadata": metadata or {},
            "vec_b64":  vec_b64,
            "added_at": time.time(),
        })
        self._save()
        log.debug("vector_memory_added", id=doc_id, text_len=len(text))
        return doc_id

    def search(
        self,
        query:    str,
        top_k:    int          = _DEFAULT_TOPK,
        filter_fn: Any | None  = None,
    ) -> list[dict]:
        """
        Recherche les documents les plus similaires à la query.

        Paramètres :
            query     : texte de recherche
            top_k     : nombre de résultats
            filter_fn : callable(doc) → bool pour filtrer les docs candidats

        Retourne :
            [{"id": ..., "text": ..., "score": float, "metadata": ...}, ...]
        """
        if not self._docs or not query.strip():
            return []

        candidates = [
            d for d in self._docs
            if filter_fn is None or filter_fn(d)
        ]
        if not candidates:
            return []

        # Encoder la query
        q_vec = self._encode(query)

        results: list[tuple[float, dict]] = []

        for doc in candidates:
            if q_vec and doc.get("vec_b64"):
                # Cosine similarity vectorielle
                try:
                    d_vec = self._b64_to_vec(doc["vec_b64"])
                    score = self._cosine(q_vec, d_vec)
                except Exception:
                    score = self._tfidf_sim(query, doc["text"])
            else:
                # Fallback TF-IDF
                score = self._tfidf_sim(query, doc["text"])

            results.append((score, doc))

        # Trier par score décroissant
        results.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id":       doc["id"],
                "text":     doc["text"],
                "score":    round(score, 4),
                "metadata": doc.get("metadata", {}),
            }
            for score, doc in results[:top_k]
            if score > 0.0
        ]

    def search_patches(self, query: str, top_k: int = 3) -> list[dict]:
        """Recherche uniquement dans les patches mémorisés."""
        return self.search(
            query, top_k=top_k,
            filter_fn=lambda d: d.get("metadata", {}).get("type") == "patch",
        )

    def search_workflows(self, query: str, top_k: int = 3) -> list[dict]:
        """Recherche uniquement dans les workflows mémorisés."""
        return self.search(
            query, top_k=top_k,
            filter_fn=lambda d: d.get("metadata", {}).get("type") == "workflow",
        )

    def get_stats(self) -> dict:
        """Retourne les statistiques de la mémoire vectorielle."""
        types: dict[str, int] = {}
        has_vec = 0
        for doc in self._docs:
            t = doc.get("metadata", {}).get("type", "unknown")
            types[t] = types.get(t, 0) + 1
            if doc.get("vec_b64"):
                has_vec += 1

        return {
            "total_docs":    len(self._docs),
            "with_vectors":  has_vec,
            "by_type":       types,
            "encoder":       _MODEL_NAME if not self._fallback else "tfidf_fallback",
            "store_path":    str(self._path),
        }

    def delete(self, doc_id: str) -> bool:
        """Supprime un document par ID. Retourne True si trouvé."""
        before = len(self._docs)
        self._docs = [d for d in self._docs if d["id"] != doc_id]
        if len(self._docs) < before:
            self._save()
            return True
        return False

    def clear(self) -> None:
        """Efface toute la mémoire (pour tests)."""
        self._docs = []
        if self._path.exists():
            self._path.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# Phase D — Qdrant backend (QDRANT_MEMORY_ENABLED=true)
# ══════════════════════════════════════════════════════════════════════════════

class QdrantVectorMemory:
    """
    Qdrant-backed vector memory.

    Implements the same add()/search() interface as VectorMemory so it can
    be used as a drop-in replacement.

    Activate: QDRANT_MEMORY_ENABLED=true
    Falls back to local VectorMemory on any Qdrant error — never raises.

    Collection: QDRANT_COLLECTION (default: bea_unified_memory)
    Vector dim:  QDRANT_VECTOR_DIM (default: 768, matches nomic-embed-text)
    """

    COLLECTION = "bea_unified_memory"
    VECTOR_DIM = 768

    def __init__(self, settings, fallback: "VectorMemory | None" = None):
        self.s = settings
        self._fallback = fallback  # VectorMemory instance used on Qdrant error
        self._encoder = None

        # Read config from settings / env
        import os
        self._qdrant_url = (
            getattr(settings, "qdrant_url", None)
            or os.environ.get("QDRANT_URL", "http://qdrant:6333")
        )
        self._qdrant_key = (
            getattr(settings, "qdrant_api_key", None)
            or os.environ.get("QDRANT_API_KEY", "") or None
        )
        self.COLLECTION = os.environ.get("QDRANT_COLLECTION", self.COLLECTION)
        self.VECTOR_DIM = int(os.environ.get("QDRANT_VECTOR_DIM", str(self.VECTOR_DIM)))

        self._ensure_collection()

    def _client(self):
        from qdrant_client import QdrantClient
        return QdrantClient(url=self._qdrant_url, api_key=self._qdrant_key)

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist. Fail silently."""
        try:
            from qdrant_client.models import Distance, VectorParams
            c = self._client()
            existing = {col.name for col in c.get_collections().collections}
            if self.COLLECTION not in existing:
                c.create_collection(
                    collection_name=self.COLLECTION,
                    vectors_config=VectorParams(
                        size=self.VECTOR_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                log.info("qdrant_collection_created",
                         collection=self.COLLECTION, dim=self.VECTOR_DIM)
        except Exception as e:
            log.warning("qdrant_ensure_collection_failed", err=str(e)[:80])

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._encoder = SentenceTransformer(_MODEL_NAME)
            except Exception as e:
                log.warning("qdrant_memory_encoder_unavailable", err=str(e)[:60])
        return self._encoder

    def _encode(self, text: str) -> list[float] | None:
        enc = self._get_encoder()
        if enc is None:
            return None
        try:
            vec = enc.encode(text, normalize_embeddings=True)
            vec_list = vec.tolist()
            # Pad to 768 if using 384-dim model
            if len(vec_list) < self.VECTOR_DIM:
                vec_list = vec_list + [0.0] * (self.VECTOR_DIM - len(vec_list))
            elif len(vec_list) > self.VECTOR_DIM:
                vec_list = vec_list[:self.VECTOR_DIM]
            return vec_list
        except Exception as e:
            log.warning("qdrant_memory_encode_error", err=str(e)[:60])
            return None

    def add(self, text: str, metadata: dict | None = None) -> str:
        """Add document. Returns doc_id. Falls back to local memory on error."""
        import hashlib
        doc_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        doc_id = f"vm_{doc_hash}"
        try:
            from qdrant_client.models import PointStruct
            vec = self._encode(text)
            if vec is None:
                raise ValueError("encoder unavailable")
            payload = {"text": text[:2000], "metadata": metadata or {}}
            self._client().upsert(
                collection_name=self.COLLECTION,
                points=[PointStruct(id=doc_hash, vector=vec, payload=payload)],
            )
            log.debug("qdrant_memory_added", id=doc_id)
            return doc_id
        except Exception as e:
            log.warning("qdrant_memory_add_fallback", err=str(e)[:80])
            if self._fallback:
                return self._fallback.add(text, metadata)
            return doc_id

    def search(
        self,
        query: str,
        top_k: int = _DEFAULT_TOPK,
        filter_fn: Any | None = None,
    ) -> list[dict]:
        """Search documents. Falls back to local memory on error."""
        try:
            vec = self._encode(query)
            if vec is None:
                raise ValueError("encoder unavailable")
            hits = self._client().search(
                collection_name=self.COLLECTION,
                query_vector=vec,
                limit=top_k,
                with_payload=True,
            )
            results = []
            for h in hits:
                payload = h.payload or {}
                doc = {
                    "id": f"vm_{h.id}",
                    "text": payload.get("text", ""),
                    "score": round(h.score, 4),
                    "metadata": payload.get("metadata", {}),
                }
                if filter_fn is None or filter_fn(doc):
                    results.append(doc)
            log.debug("qdrant_memory_search",
                      query=query[:40], results=len(results))
            return results
        except Exception as e:
            log.warning("qdrant_memory_search_fallback", err=str(e)[:80])
            if self._fallback:
                return self._fallback.search(query, top_k=top_k, filter_fn=filter_fn)
            return []

    def get_stats(self) -> dict:
        try:
            info = self._client().get_collection(self.COLLECTION)
            return {
                "backend": "qdrant",
                "collection": self.COLLECTION,
                "total_docs": info.points_count or 0,
                "qdrant_url": self._qdrant_url,
            }
        except Exception as e:
            return {"backend": "qdrant", "error": str(e)[:80]}


def _qdrant_memory_enabled() -> bool:
    """Check QDRANT_MEMORY_ENABLED env var. Default: false."""
    import os
    return os.environ.get("QDRANT_MEMORY_ENABLED", "false").lower() in ("1", "true", "yes")


def get_vector_memory(settings) -> "VectorMemory | QdrantVectorMemory":
    """
    Factory: returns QdrantVectorMemory when QDRANT_MEMORY_ENABLED=true,
    otherwise returns VectorMemory (local numpy fallback).

    QdrantVectorMemory itself falls back to local VectorMemory on any error,
    so this factory is safe to call unconditionally.
    """
    local = VectorMemory(settings)
    if _qdrant_memory_enabled():
        try:
            qvm = QdrantVectorMemory(settings, fallback=local)
            log.info("vector_memory_backend", backend="qdrant")
            return qvm
        except Exception as e:
            log.warning("qdrant_memory_init_failed_fallback_local",
                        err=str(e)[:80])
    log.debug("vector_memory_backend", backend="local")
    return local
