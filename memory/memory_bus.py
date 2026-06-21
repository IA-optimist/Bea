"""
BEA MAX — MemoryBus
Interface unifiée pour les 4 systèmes de mémoire de Bea.

Problème résolu :
    Les agents doivent actuellement importer et instancier séparément
    MemoryStore, VectorMemory, PatchMemory, FailureMemory.
    MemoryBus centralise tout en un seul point d'accès avec routing intelligent.

Architecture :
    MemoryBus
    ├── MemoryStore    (PostgreSQL/Redis/in-memory — clé-valeur, tags, recherche texte)
    ├── VectorMemory   (embeddings locaux — similarité sémantique)
    ├── PatchMemory    (patterns de patchs réussis — guide PatchBuilder)
    └── FailureMemory  (patchs rejetés — évite les erreurs répétées)

Interface principale :
    bus = MemoryBus(settings)

    # Stockage multi-backend
    bus.remember(text, metadata, tags, backends)
    bus.remember_patch(patch, success, model)     # PatchMemory + FailureMemory

    # Recherche unifiée
    results = await bus.search(query, top_k, backends)
    context = bus.get_patch_context(file, category)  # pour PatchBuilder

    # Accès direct aux sous-systèmes (escape hatch)
    bus.store         # MemoryStore
    bus.vector        # VectorMemory
    bus.patches       # PatchMemory
    bus.failures      # FailureMemory

Backends constants :
    BACKEND_STORE   = "store"
    BACKEND_VECTOR  = "vector"
    BACKEND_PATCHES = "patches"
    BACKEND_FAILURE = "failures"
    BACKEND_ALL     = ("store", "vector")   # backends généraux
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
import structlog

log = structlog.get_logger(__name__)

# ── Constantes backend ────────────────────────────────────────
BACKEND_STORE    = "store"
BACKEND_VECTOR   = "vector"
BACKEND_PATCHES  = "patches"
BACKEND_FAILURE  = "failures"
BACKEND_PGVECTOR = "pgvector"
BACKEND_FTS      = "fts"  # opt-in (BEA_FTS_DB), hors BACKEND_ALL
BACKEND_QDRANT_BEAMAX = "qdrant_beamax"
BACKEND_ALL      = (BACKEND_STORE, BACKEND_VECTOR, BACKEND_QDRANT_BEAMAX)


class MemoryBus:
    """
    Bus d'accès unifié aux 4 systèmes de mémoire de Bea.

    Tous les sous-systèmes sont initialisés en lazy (à la première utilisation)
    pour éviter les imports inutiles si certains backends ne sont pas disponibles.

    Usage recommandé dans les agents :
        bus = MemoryBus(settings)
        bus.remember("résumé mission X", metadata={"type": "mission"})
        results = await bus.search("mission CBD France")
        bus.remember_patch(patch, success=True, model="deepseek-coder-v2")
        context = bus.get_patch_context("self_improve/auditor.py")
    """

    def __init__(self, settings):
        self.s = settings
        self._store    = None
        self._vector   = None
        self._patches  = None
        self._failures = None
        self._pgvector = None
        self._qdrant_beamax = None
        self._agent_memory = None  # Phase 2
        self._knowledge    = None  # Phase 2

    # ── Accesseurs lazy ───────────────────────────────────────

    @property
    def store(self):
        """MemoryStore — clé-valeur, PostgreSQL/Redis/in-memory."""
        if self._store is None:
            try:
                from memory.store import MemoryStore
                self._store = MemoryStore(self.s)
            except Exception as e:
                log.warning("memory_bus_store_init_failed", err=str(e))
        return self._store

    @property
    def vector(self):
        """VectorMemory — similarité sémantique par embeddings."""
        if self._vector is None:
            try:
                from memory.vector_memory import VectorMemory
                self._vector = VectorMemory(self.s)
            except Exception as e:
                log.warning("memory_bus_vector_init_failed", err=str(e))
        return self._vector

    @property
    def patches(self):
        """PatchMemory — patterns de patchs réussis."""
        if self._patches is None:
            try:
                from memory.patch_memory import PatchMemory
                self._patches = PatchMemory(self.s)
            except Exception as e:
                log.warning("memory_bus_patches_init_failed", err=str(e))
        return self._patches

    @property
    def failures(self):
        """FailureMemory — patchs rejetés / erreurs passées."""
        if self._failures is None:
            try:
                from memory.failure_memory import FailureMemory
                self._failures = FailureMemory(self.s)
            except Exception as e:
                log.warning("memory_bus_failures_init_failed", err=str(e))
        return self._failures

    @property
    def pgvector(self):
        """VectorStore (pgvector) — similarité sémantique via PostgreSQL."""
        if self._pgvector is None:
            try:
                from memory.vector_store import VectorStore
                self._pgvector = VectorStore(self.s)
            except Exception as e:
                log.warning("memory_bus_pgvector_init_failed", err=str(e))
        return self._pgvector

    # ── Recall (unified retrieval) ────────────────────────────

    @property
    def qdrant_beamax(self):
        """Canonical Qdrant recall over beamax_memory_384."""
        if self._qdrant_beamax is None:
            try:
                from memory.qdrant_recall import QdrantMemoryRecall, config_from_settings

                self._qdrant_beamax = QdrantMemoryRecall(config_from_settings(self.s))
            except Exception as e:
                log.warning("memory_bus_qdrant_beamax_init_failed", err=str(e)[:80])
        return self._qdrant_beamax

    async def recall(
        self,
        query:     str,
        top_k:     int   = 5,
        semantic:  bool  = True,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Unified retrieval across all available backends.

        Priority cascade:
          1. Exact key match in MemoryStore
          2. Local VectorMemory (fast, in-process)
          3. pgvector augmentation (semantic, PostgreSQL)

        Returns list of result dicts with keys:
            {id, text, score, metadata, backend}
        """
        results: list[dict] = []

        # 1. Exact key in MemoryStore
        if self.store:
            try:
                retrieve = getattr(self.store, "retrieve", None)
                if callable(retrieve):
                    val = await retrieve(query)
                    if val:
                        results.append({
                            "id":       query,
                            "text":     str(val),
                            "score":    1.0,
                            "metadata": {},
                            "backend":  BACKEND_STORE,
                        })
            except Exception as _exc:
                log.warning("swallowed_exception", action="track_memory_failure", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        if not semantic:
            return results[:top_k]

        # 2. Canonical Qdrant memory seeded for Bea self-knowledge
        if self.qdrant_beamax:
            try:
                qdrant_hits = self.qdrant_beamax.search(
                    query,
                    top_k=top_k,
                    min_score=min_score,
                )
                results.extend(qdrant_hits)
            except Exception as e:
                log.warning("recall_qdrant_beamax_failed", err=str(e)[:80])

        # 3. Local VectorMemory
        if self.vector:
            try:
                loop = asyncio.get_running_loop()
                local_hits = await loop.run_in_executor(
                    None,
                    lambda: self.vector.search(query, top_k=top_k),
                )
                for r in local_hits:
                    if r.get("score", 0) >= min_score:
                        r.setdefault("backend", BACKEND_VECTOR)
                        results.append(r)
            except Exception as e:
                log.warning("recall_vector_failed", err=str(e)[:80])

        # 4. pgvector augmentation
        if self.pgvector and self.pgvector.is_available():
            try:
                from memory.embeddings import EmbeddingProvider
                ep  = EmbeddingProvider(self.s)
                vec = await ep.embed(query)
                pg_hits = await self.pgvector.search_similar(
                    embedding=vec,
                    top_k=top_k,
                    min_score=min_score,
                )
                for r in pg_hits:
                    results.append({
                        "id":       r["id"],
                        "text":     r["content"],
                        "score":    r["score"],
                        "metadata": r.get("metadata", {}),
                        "backend":  BACKEND_PGVECTOR,
                    })
            except Exception as e:
                log.warning("recall_pgvector_failed", err=str(e)[:80])

        # Deduplicate by text prefix, sort by score descending
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in sorted(results, key=lambda x: x.get("score", 0.0), reverse=True):
            key = str(r.get("text", ""))[:100]
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        return deduped[:top_k]

    # ── Stockage ──────────────────────────────────────────────

    def remember(
        self,
        text:     str,
        metadata: dict | None           = None,
        tags:     list[str] | None      = None,
        backends: tuple[str, ...] | None = None,
        key:      str                   = "",
    ) -> dict[str, str]:
        """
        Stocke un texte dans les backends spécifiés (synchrone).

        Paramètres :
            text     : contenu à mémoriser
            metadata : dict de métadonnées (type, agent, session_id…)
            tags     : tags pour MemoryStore
            backends : tuple de BACKEND_* ; défaut = BACKEND_ALL
            key      : clé explicite pour MemoryStore (auto si vide)

        Retourne :
            dict[backend_name, doc_id_ou_key]
        """
        if not text or not text.strip():
            return {}

        active   = backends or BACKEND_ALL
        results: dict[str, str] = {}
        meta     = metadata or {}

        if BACKEND_VECTOR in active and self.vector:
            try:
                doc_id = self.vector.add(text, meta)
                results[BACKEND_VECTOR] = doc_id
            except Exception as e:
                log.warning("memory_bus_vector_store_failed", err=str(e))

        if BACKEND_STORE in active and self.store:
            try:
                k = key or f"mem_{int(time.time() * 1000)}"
                # MemoryStore.store() est async.
                # asyncio.ensure_future() échoue silencieusement hors contexte async.
                # On utilise get_running_loop() pour détecter le contexte.
                try:
                    loop = asyncio.get_running_loop()
                    # On est dans un contexte async — planifier en fire-and-forget
                    loop.create_task(self.store.store(k, text, tags=tags or []))
                except RuntimeError:
                    # No running loop — spin a fresh loop (no nesting risk)
                    _loop = asyncio.new_event_loop()
                    try:
                        _loop.run_until_complete(
                            self.store.store(k, text, tags=tags or [])
                        )
                    finally:
                        _loop.close()
                results[BACKEND_STORE] = k
            except Exception as e:
                log.warning("memory_bus_store_failed", err=str(e))

        return results

    async def remember_async(
        self,
        text:     str,
        metadata: dict | None           = None,
        tags:     list[str] | None      = None,
        backends: tuple[str, ...] | None = None,
        key:      str                   = "",
    ) -> dict[str, str]:
        """Version async de remember() — attendre la confirmation MemoryStore."""
        if not text or not text.strip():
            return {}

        active   = backends or BACKEND_ALL
        results: dict[str, str] = {}
        meta     = metadata or {}

        if BACKEND_VECTOR in active and self.vector:
            try:
                doc_id = self.vector.add(text, meta)
                results[BACKEND_VECTOR] = doc_id
            except Exception as e:
                log.warning("memory_bus_vector_store_failed", err=str(e))

        if BACKEND_STORE in active and self.store:
            try:
                k = key or f"mem_{int(time.time() * 1000)}"
                await self.store.store(k, text, tags=tags or [])
                results[BACKEND_STORE] = k
            except Exception as e:
                log.warning("memory_bus_store_failed", err=str(e))

        return results

    def remember_patch(
        self,
        patch,
        success: bool = True,
        model:   str  = "",
    ) -> None:
        """
        Enregistre le résultat d'un patch dans PatchMemory ou FailureMemory.

        success=True  → PatchMemory.record_success()
        success=False → FailureMemory.record_rejection()
        """
        if success:
            if self.patches:
                try:
                    self.patches.record_success(patch, model=model)
                except Exception as e:
                    log.warning("memory_bus_patch_success_failed", err=str(e))
        else:
            if self.failures:
                try:
                    reason = getattr(patch, "apply_error", "") or getattr(patch, "review_notes", "rejected")
                    self.failures.record_rejection(patch, reason=reason or "rejected", model=model)
                except Exception as e:
                    log.warning("memory_bus_patch_failure_failed", err=str(e))

    # ── Recherche ─────────────────────────────────────────────

    _fts = None

    @property
    def fts(self):
        """FTSRecall — rappel plein-texte SQLite, opt-in via env BEA_FTS_DB."""
        if self._fts is None:
            import os
            db = os.getenv("BEA_FTS_DB")
            if not db:
                return None
            try:
                from memory.fts_recall import FTSRecall
                self._fts = FTSRecall(db)
            except Exception as e:
                log.warning("memory_bus_fts_init_failed", err=str(e))
                return None
        return self._fts

    async def _search_fts(self, query: str, top_k: int) -> list[dict]:
        hits = self.fts.search(query, limit=top_k)
        return [
            {"id": "", "text": h.get("content", ""), "score": 0.5,
             "metadata": {"kind": h.get("kind", ""),
                          "session_id": h.get("session_id", "")}}
            for h in hits
        ]

    async def search(
        self,
        query:    str,
        top_k:    int                   = 5,
        backends: tuple[str, ...] | None = None,
    ) -> list[dict]:
        """
        Recherche unifiée sur tous les backends spécifiés.
        Les résultats de VectorMemory et MemoryStore sont fusionnés et
        triés par score décroissant.

        Chaque résultat contient :
            {"id", "text", "score", "metadata", "backend"}

        Paramètres :
            query    : texte de recherche
            top_k    : nombre de résultats par backend (doublons cross-backends possibles)
            backends : tuple de BACKEND_* ; défaut = BACKEND_ALL
        """
        active  = backends or BACKEND_ALL
        results: list[dict] = []

        tasks: list[tuple[str, Any]] = []

        if BACKEND_VECTOR in active and self.vector:
            tasks.append((BACKEND_VECTOR, self._search_vector(query, top_k)))

        if BACKEND_STORE in active and self.store:
            tasks.append((BACKEND_STORE, self._search_store(query, top_k)))

        if BACKEND_QDRANT_BEAMAX in active and self.qdrant_beamax:
            tasks.append((BACKEND_QDRANT_BEAMAX, self._search_qdrant_beamax(query, top_k)))

        # pgvector augmentation — always attempted when available, even if not in BACKEND_ALL.
        # Provides semantic PostgreSQL results alongside local vector results.
        if self.pgvector and self.pgvector.is_available():
            tasks.append((BACKEND_PGVECTOR, self._search_pgvector(query, top_k)))

        if BACKEND_FTS in active and self.fts:
            tasks.append((BACKEND_FTS, self._search_fts(query, top_k)))

        # Exécuter en parallèle
        if tasks:
            coros      = [t[1] for t in tasks]
            names      = [t[0] for t in tasks]
            raw_results = await asyncio.gather(*coros, return_exceptions=True)

            for name, raw in zip(names, raw_results):
                if isinstance(raw, Exception):
                    log.warning("memory_bus_search_failed",
                                backend=name, err=str(raw))
                    continue
                for item in raw:
                    item["backend"] = name
                    results.append(item)

        # Déduplicate par texte + trier par score
        seen: set[str] = set()
        deduped: list[dict] = []
        for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
            key = r.get("text", "")[:100]
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        return deduped[:top_k]

    async def _search_vector(self, query: str, top_k: int) -> list[dict]:
        """Recherche VectorMemory (sync dans executor pour ne pas bloquer)."""
        if not self.vector:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.vector.search(query, top_k=top_k),
        )

    async def _search_pgvector(self, query: str, top_k: int) -> list[dict]:
        """
        Semantic search via pgvector (PostgreSQL).
        Returns [] silently if pgvector is unavailable or embedding fails.
        """
        if not self.pgvector or not self.pgvector.is_available():
            return []
        try:
            from memory.embeddings import EmbeddingProvider
            ep  = EmbeddingProvider(self.s)
            vec = await ep.embed(query)
            hits = await self.pgvector.search_similar(
                embedding=vec,
                top_k=top_k,
                min_score=0.4,
            )
            return [
                {
                    "id":       r["id"],
                    "text":     r.get("content", ""),
                    "score":    r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                }
                for r in hits
            ]
        except Exception as exc:
            log.debug("memory_bus_pgvector_search_skip", err=str(exc)[:80])
            return []

    async def _search_qdrant_beamax(self, query: str, top_k: int) -> list[dict]:
        """Semantic search over canonical beamax_memory_384."""
        if not self.qdrant_beamax:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.qdrant_beamax.search(query, top_k=top_k, min_score=0.2),
        )

    async def _search_store(self, query: str, top_k: int) -> list[dict]:
        """Recherche MemoryStore."""
        if not self.store:
            return []
        try:
            raw = await self.store.search(query, k=top_k)  # MemoryStore uses `k`, not `top_k`
            # MemoryStore retourne list[dict] avec "key", "text", "score"
            return [
                {
                    "id":       r.get("key", ""),
                    "text":     r.get("text", ""),
                    "score":    r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                }
                for r in raw
            ]
        except Exception as e:
            log.warning("memory_bus_store_search_failed", err=str(e))
            return []

    # ── Contexte pour PatchBuilder ────────────────────────────

    def get_patch_context(self, file: str, category: str = "") -> str:
        """
        Construit un bloc de contexte injecté dans le prompt de PatchBuilder.
        Combine : patterns de succès (PatchMemory) + échecs passés (FailureMemory).

        Retourne chaîne vide si aucun historique disponible.
        """
        parts: list[str] = []

        if self.failures:
            try:
                ctx = self.failures.get_context(file)
                if ctx:
                    parts.append(ctx)
            except Exception as e:
                log.warning("memory_bus_failure_context_failed", err=str(e))

        if self.patches:
            try:
                ctx = self.patches.get_context(file=file, category=category)
                if ctx:
                    parts.append(ctx)
            except Exception as e:
                log.warning("memory_bus_patch_context_failed", err=str(e))

        return "\n".join(parts)

    def has_failed_before(self, patch) -> bool:
        """Délègue à FailureMemory — True si ce patch a déjà été rejeté."""
        if self.failures:
            try:
                return self.failures.has_failed_before(patch)
            except Exception as _exc:
                log.warning("swallowed_exception", action="failures_has_failed_before", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return False

    def best_model_for(self, category: str) -> str | None:
        """Retourne le modèle LLM le plus performant pour une catégorie (PatchMemory)."""
        if self.patches:
            try:
                return self.patches.get_best_model(category)
            except Exception as _exc:
                log.warning("swallowed_exception", action="patches_get_best_model", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return None

    # ── Statistiques ──────────────────────────────────────────

    def get_stats(self) -> dict:
        """Statistiques agrégées de tous les backends disponibles."""
        stats: dict[str, Any] = {}

        if self._vector:
            try:
                stats["vector"] = self._vector.get_stats()
            except Exception as _exc:
                log.warning("swallowed_exception", action="vector_stats", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        if self._patches:
            try:
                stats["patches"] = self._patches.get_stats()
            except Exception as _exc:
                log.warning("swallowed_exception", action="patches_stats", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        if self._failures:
            try:
                stats["failures"] = self._failures.get_stats()
            except Exception as _exc:
                log.warning("swallowed_exception", action="failures_stats", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return stats

    def get_stats_report(self) -> str:
        """Rapport texte des statistiques de mémoire."""
        s = self.get_stats()
        lines = ["=== MemoryBus Stats ==="]

        if "vector" in s:
            v = s["vector"]
            lines.append(
                f"Vector  : {v.get('total_docs', 0)} docs  "
                f"({v.get('with_vectors', 0)} vectorisés)  "
                f"encoder={v.get('encoder', '?')}"
            )

        if "patches" in s:
            p = s["patches"]
            lines.append(
                f"Patches : {p.get('total', 0)} succès  "
                f"(top model: {list(p.get('by_model', {}).keys())[:1] or 'N/A'})"
            )

        if "failures" in s:
            f = s["failures"]
            lines.append(
                f"Failures: {f.get('total', 0)} rejets  "
                f"(top raison: {list(f.get('top_reasons', {}).keys())[:1] or 'N/A'})"
            )

        return "\n".join(lines)


    # ==========================================================================
    # PHASE 2 - Canonical API  (store / retrieve / update / build_agent_context)
    # ==========================================================================

    def store_memory(self, text, memory_type="knowledge", layer="",
                     mission_id="", agent_id="", confidence=1.0,
                     tags=None, source="", metadata=None):
        """Single entry point for all memory writes. Routes by layer.

        Renamed from 'store' to avoid shadowing the @property def store
        (which returns the MemoryStore backend instance). Bug: the method
        definition at class level overrides the property, making self.store
        return a bound method instead of a MemoryStore, breaking search().
        """
        from memory.schemas import (MemoryEntry, MemoryType, MemoryLayer,
                                    LAYER_FOR_TYPE, normalize_metadata)
        try:
            mt = MemoryType(memory_type)
        except ValueError:
            mt = MemoryType.KNOWLEDGE
        if not layer:
            rl = LAYER_FOR_TYPE.get(mt, MemoryLayer.SEMANTIC)
        else:
            try:
                rl = MemoryLayer(layer)
            except ValueError:
                rl = MemoryLayer.SEMANTIC
        entry = MemoryEntry(text=text, memory_type=mt, layer=rl,
                            mission_id=mission_id, agent_id=agent_id,
                            confidence=confidence, tags=tags or [],
                            source=source, metadata=metadata or {})
        meta = normalize_metadata(entry.metadata, entry)
        if rl.value == "working":
            backends = ("store",)
        elif rl.value == "episodic":
            backends = BACKEND_ALL
        else:
            backends = ("vector",)
        self.remember(text, metadata=meta, tags=entry.tags,
                      backends=backends, key=entry.id)
        log.info("memory.store", entry_id=entry.id, layer=rl.value,
                 memory_type=mt.value, mission_id=mission_id,
                 agent_id=agent_id, chars=len(text))
        return entry.id

    async def retrieve(self, query, layer="", memory_type="",
                       top_k=5, min_score=0.0, mission_id=""):
        """Unified retrieval with layer/type/mission filtering."""
        results = await self.recall(query, top_k=top_k * 2, min_score=min_score)
        out = []
        for r in results:
            meta = r.get("metadata", {})
            if layer and meta.get("layer", "") != layer:
                continue
            if memory_type and meta.get("memory_type", "") != memory_type:
                continue
            if mission_id and meta.get("mission_id", "") not in ("", mission_id):
                continue
            out.append(r)
        log.debug("memory.retrieve", query=query[:60], layer=layer,
                  top_k=top_k, returned=len(out[:top_k]))
        return out[:top_k]

    async def update(self, entry_id, text="", metadata=None, confidence=-1.0):
        """Update an existing memory entry (re-add with same key)."""
        if text and self.vector:
            try:
                meta = metadata or {}
                if confidence >= 0:
                    meta["confidence"] = confidence
                self.vector.add(text, metadata=meta)
                log.info("memory.update", entry_id=entry_id, chars=len(text))
                return True
            except Exception as e:
                log.warning("memory.update_failed", entry_id=entry_id, err=str(e)[:80])
        return False

    def build_agent_context(self, agent_id, mission_id="", max_items=5):
        """Builds injectable memory context string for an agent prompt."""
        parts = []
        if self._agent_memory is None:
            try:
                from memory.agent_memory import AgentMemory as AM
                self._agent_memory = AM(self.s)
            except Exception as e:
                log.debug("memory_bus_agent_memory_init", err=str(e)[:60])
        if self._agent_memory:
            try:
                ctx = self._agent_memory.get_context(agent_id, max_items=max_items)
                if ctx:
                    parts.append(ctx)
            except Exception as e:
                log.debug("memory_bus_agent_ctx_failed", err=str(e)[:60])
        if self._knowledge is None:
            try:
                from memory.legacy_knowledge_memory import KnowledgeMemory
                self._knowledge = KnowledgeMemory(self.s)
            except Exception as e:
                log.debug("memory_bus_knowledge_init", err=str(e)[:60])
        if self._knowledge:
            try:
                entries = self._knowledge.get_for_agent(agent_id, top_k=3)
                if entries:
                    lines = ["## Connaissances procedurales"]
                    for e in entries:
                        lines.append("- [%s] %s" % (e.get("type","?"), e.get("solution","")[:200]))
                    parts.append("\n".join(lines))
            except Exception as e:
                log.debug("memory_bus_knowledge_ctx_failed", err=str(e)[:60])
        return "\n\n".join(parts)

    def get_layer_stats(self):
        """Memory stats broken down by layer (for /status API)."""
        base = self.get_stats()
        vec_count = base.get("vector", {}).get("total_docs", 0)
        patch_count = base.get("patches", {}).get("total", 0)
        return {
            "layers": {
                "working":    {"backend": "store"},
                "episodic":   {"backend": "store+vector", "entries": vec_count},
                "semantic":   {"backend": "vector+pgvector", "entries": vec_count},
                "procedural": {"backend": "vector", "entries": patch_count},
            },
            "backends": base,
        }

    async def close(self) -> None:
        """Ferme les connexions (pool PG du MemoryStore)."""
        if self._store:
            try:
                await self._store.close()
            except Exception as _exc:
                log.warning("swallowed_exception", action="store_close", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ==========================================================================
    # PHASE 4 — Layer-based API (additive, fail-open)
    # ==========================================================================

    LAYERS = [
        "short_term", "working_memory", "long_term",
        "knowledge_index", "episodic", "procedural", "semantic",
    ]

    @property
    def _layers_store(self) -> dict:
        """Lazy in-memory dict keyed by layer name."""
        if not hasattr(self, "_layers_data"):
            object.__setattr__(self, "_layers_data", {})
        return self._layers_data  # type: ignore[attr-defined]

    def add(self, layer: str, entry: dict) -> None:
        """Append an entry dict to the named layer."""
        store = self._layers_store
        if layer not in store:
            store[layer] = []
        store[layer].append(dict(entry))
        # Debounced flush every _FLUSH_INTERVAL writes
        try:
            MemoryBus._write_count += 1
            if MemoryBus._write_count >= MemoryBus._FLUSH_INTERVAL:
                MemoryBus._write_count = 0
                self._flush()
        except Exception as _exc:
            log.warning("swallowed_exception", action="write_flush", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def add_with_ttl(self, layer: str, entry: dict, ttl_seconds: int) -> None:
        """Store entry with expiry timestamp. Entry is auto-removed on next read if expired."""
        entry = dict(entry)
        entry["_expires_at"] = time.time() + ttl_seconds
        self.add(layer, entry)

    def add_priority(self, layer: str, entry: dict, priority: int = 5) -> None:
        """Store entry with priority tag (1=low, 10=high). Used for context selection."""
        entry = dict(entry)
        entry["_priority"] = max(1, min(10, priority))
        self.add(layer, entry)

    def get_recent(self, layer: str, n: int = 10, exclude_expired: bool = True) -> list[dict]:
        """Get most recent N entries from a layer, optionally filtering expired ones."""
        try:
            entries = list(self._layers_store.get(layer, []))
            if exclude_expired:
                now = time.time()
                entries = [
                    e for e in entries
                    if e.get("_expires_at", float("inf")) > now
                ]
            return entries[-n:]
        except Exception:
            return []

    def get_by_priority(self, layer: str, min_priority: int = 5) -> list[dict]:
        """Get entries with _priority >= min_priority."""
        try:
            now = time.time()
            entries = [
                e for e in self._layers_store.get(layer, [])
                if e.get("_priority", 0) >= min_priority
                and e.get("_expires_at", float("inf")) > now
            ]
            return sorted(entries, key=lambda x: x.get("_priority", 0), reverse=True)
        except Exception:
            return []

    def get_layer_size(self, layer: str) -> int:
        """Return count of entries in a layer."""
        try:
            return len(self._layers_store.get(layer, []))
        except Exception:
            return 0

    def clear_expired(self) -> int:
        """Remove all expired entries from all layers. Returns count removed."""
        removed = 0
        try:
            now = time.time()
            store = self._layers_store
            for layer in list(store.keys()):
                before = len(store[layer])
                store[layer] = [
                    e for e in store[layer]
                    if e.get("_expires_at", float("inf")) > now
                ]
                removed += before - len(store[layer])
        except Exception as _exc:
            log.warning("swallowed_exception", action="layer_expire_sweep", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return removed

    @classmethod
    def get_instance(cls) -> "MemoryBus":
        """Singleton accessor — uses minimal settings if none available."""
        if not hasattr(cls, "_singleton") or cls._singleton is None:
            try:
                from config.settings import get_settings
                settings = get_settings()
            except Exception:
                settings = type("_Settings", (), {})()
            inst = cls(settings)
            inst._load_cache()  # restore persisted layer data
            cls._singleton = inst
        return cls._singleton

    # ── Layer cache persistence (fail-open) ───────────────────

    _CACHE_PATH = Path("workspace/layer_cache.json")
    _write_count = 0
    _FLUSH_INTERVAL = 10  # flush every N writes

    def _flush(self) -> None:
        """Persist layer data to disk. Fail-open."""
        try:
            import json as _json
            self._CACHE_PATH.parent.mkdir(exist_ok=True)
            with open(self._CACHE_PATH, "w", encoding="utf-8") as f:
                _json.dump(self._layers_store, f, default=str)
        except Exception as _exc:
            log.warning("swallowed_exception", action="cache_save", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def _load_cache(self) -> None:
        """Load persisted layer data on startup. Fail-open."""
        try:
            import json as _json
            if self._CACHE_PATH.exists():
                data = _json.loads(self._CACHE_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    object.__setattr__(self, "_layers_data", data)
        except Exception as _exc:
            log.warning("swallowed_exception", action="cache_load", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
