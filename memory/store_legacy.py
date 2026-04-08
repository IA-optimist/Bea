"""
JARVIS MAX — Memory Store v2
Mémoire vectorielle persistante (Qdrant) avec fallback PostgreSQL.

Corrections v2 :
- VECTOR_DIM dynamique : all-MiniLM-L6-v2 produit 384 dims, pas 1536.
  L'ancien padding silencieux 384→1536 faussait tous les scores cosine.
- asyncio.get_running_loop() remplace get_event_loop() (déprécié Python 3.10+).
- Chargement SentenceTransformer via run_in_executor avec timeout (120s).
  Sans ça, le premier démarrage bloque la boucle asyncio entière.
- Erreurs réseau au premier téléchargement du modèle : gérées explicitement,
  avec flag _LOCAL_MODEL_FAILED pour éviter de retenter à chaque appel.
- Fallback OpenAI→local si OpenAI échoue (réseau down, quota, etc.).
"""
from __future__ import annotations

import asyncio
import hashlib

import structlog

log = structlog.get_logger()

SCORE_THRESH = 0.55

# Noms de collections séparés par dimension — évite toute pollution cross-mode.
_COLLECTION_384  = "jarvismax_memory_384"
_COLLECTION_1536 = "jarvismax_memory_1536"

# ── Dimensions d'embedding ──────────────────────────────────────
# all-MiniLM-L6-v2  → 384 dims  (sentence-transformers, local)
# text-embedding-3-small → 1536 dims  (OpenAI)
# Ces deux valeurs sont incompatibles : une collection Qdrant a UNE dimension fixe.
# Si tu changes de mode (local → OpenAI), recrée la collection ou utilise
# un nom de collection différent.
_LOCAL_MODEL_NAME  = "all-MiniLM-L6-v2"
_LOCAL_VECTOR_DIM  = 384
_OPENAI_VECTOR_DIM = 1536

# Cache module-level : SentenceTransformer prend ~1-2s et ~100MB RAM au chargement.
_LOCAL_MODEL_CACHE: dict[str, object] = {}
# Modèles dont le chargement a définitivement échoué (pas de réseau, package manquant).
# Évite de retenter à chaque appel et de bloquer asyncio.
_LOCAL_MODEL_FAILED: set[str] = set()


class MemoryStore:

    def __init__(self, settings):
        self.s        = settings
        self._client  = None
        self._pg_pool = None   # asyncpg connection pool — lazy, shared

    # ── Public API ────────────────────────────────────────────

    async def store(self, key: str, text: str, tags: list[str] | None = None):
        client = await self._get_client()
        if client:
            await self._qdrant_store(client, key, text, tags or [])
        else:
            await self._pg_store(key, text, tags or [])

    async def search(self, query: str, k: int = 5) -> list[str]:
        client = await self._get_client()
        if client:
            return await self._qdrant_search(client, query, k)
        return await self._pg_search(query, k)

    async def store_session(self, session) -> None:
        """Mémorise le résumé d'une session terminée."""
        key  = f"session:{session.session_id}"
        text = (
            f"Session {session.session_id} "
            f"Mission : {session.mission_summary}\n"
            f"Mode : {session.mode}\n"
            f"Résultat : {session.final_report[:400]}"
        )
        await self.store(key, text, tags=["session", "history", session.mode])

    async def index_workspace(self, workspace_dir) -> int:
        """Indexe les fichiers texte du workspace en mémoire."""
        from pathlib import Path
        indexed = 0
        ws = Path(workspace_dir)
        for ext in ("*.md", "*.txt"):
            for p in ws.rglob(ext):
                try:
                    text = p.read_text("utf-8", errors="replace")[:3000]
                    await self.store(f"file:{p.name}", text, tags=["workspace", p.suffix])
                    indexed += 1
                except Exception:
                    pass
        log.info("workspace_indexed", count=indexed)
        return indexed

    # ── Qdrant ────────────────────────────────────────────────

    async def _get_client(self):
        # Ne pas cacher les échecs : Qdrant peut revenir après un redémarrage
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import AsyncQdrantClient
            _qdrant_kwargs: dict = {
                "host": self.s.qdrant_host,
                "port": self.s.qdrant_port,
                "timeout": 5,
            }
            # Authentification Qdrant via API key (recommandé en production)
            if getattr(self.s, "qdrant_api_key", ""):
                _qdrant_kwargs["api_key"] = self.s.qdrant_api_key
                # Force HTTP for internal Docker network (api_key triggers HTTPS by default)
                if not getattr(self.s, "qdrant_https", False):
                    _qdrant_kwargs["https"] = False
            c = AsyncQdrantClient(**_qdrant_kwargs)
            await self._ensure_collection(c)
            self._client = c
            log.info("qdrant_connected")
            return self._client
        except Exception as e:
            log.warning("qdrant_unavailable", err=str(e))
            self._client = None  # None = retry au prochain appel
            return None

    def _vector_dim(self) -> int:
        """Dimension selon le mode d'embedding actif."""
        return _OPENAI_VECTOR_DIM if self.s.openai_api_key else _LOCAL_VECTOR_DIM

    def _collection_name(self) -> str:
        """
        Nom de collection incluant la dimension pour éviter tout mismatch.
        Une clé openai_api_key → collection _1536.
        Sans clé → collection _384.
        Les deux collections peuvent coexister en Qdrant sans conflit.
        """
        return _COLLECTION_1536 if self.s.openai_api_key else _COLLECTION_384

    async def _ensure_collection(self, client) -> None:
        """
        Garantit que la collection Qdrant existe avec la bonne dimension.

        Stratégie :
          - Nom de collection unique par dimension → aucun mismatch possible
          - Si la collection existe déjà avec la bonne dim → rien à faire
          - Si elle existe avec une mauvaise dim (ne devrait plus arriver) → recréer
          - Si elle n'existe pas → créer
        """
        from qdrant_client.models import Distance, VectorParams
        name = self._collection_name()
        dim  = self._vector_dim()

        try:
            info     = await client.get_collection(name)
            existing = info.config.params.vectors.size
            if existing == dim:
                log.debug("qdrant_collection_ok", name=name, dim=dim)
                return
            # Mismatch résiduel (impossible avec noms dimension-aware, mais défense)
            log.warning(
                "qdrant_dim_mismatch_recreating",
                name=name, existing=existing, expected=dim,
            )
            await client.delete_collection(name)
        except Exception:
            pass  # collection inexistante → créer

        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        log.info("qdrant_collection_created", name=name, dim=dim)

    async def _qdrant_store(self, client, key: str, text: str, tags: list[str]):
        from qdrant_client.models import PointStruct
        try:
            vec = await self._embed(text)
            if not vec:
                # embed() a retourné None → mode incohérent (ex: OpenAI down en mode 1536)
                # Ne pas insérer — éviter une corruption de collection
                log.warning("qdrant_store_skipped_no_vector", key=key)
                await self._pg_store(key, text, tags)
                return
            point_id = int(hashlib.md5(key.encode()).hexdigest()[:8], 16)
            await client.upsert(
                collection_name=self._collection_name(),
                points=[PointStruct(
                    id=point_id, vector=vec,
                    payload={"key": key, "text": text, "tags": tags},
                )],
            )
        except Exception as e:
            log.warning("qdrant_store_failed", key=key, err=str(e))
            await self._pg_store(key, text, tags)

    async def _qdrant_search(self, client, query: str, k: int) -> list[str]:
        try:
            vec = await self._embed(query)
            if not vec:
                return await self._pg_search(query, k)
            # qdrant-client >= 1.7 : search() supprimé → query_points()
            # Retourne QueryResponse ; .points = List[ScoredPoint]
            response = await client.query_points(
                collection_name=self._collection_name(),
                query=vec,
                limit=k,
                score_threshold=SCORE_THRESH,
            )
            return [r.payload.get("text", "") for r in response.points]
        except Exception as e:
            log.warning("qdrant_search_failed", err=str(e))
            return await self._pg_search(query, k)

    # ── Embeddings ────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float] | None:
        """
        Produit un vecteur d'embedding cohérent avec la dimension de la collection.

        Mode OpenAI (openai_api_key défini) :
            → embed OpenAI 1536 dims UNIQUEMENT.
            → Si OpenAI échoue : retourne None (pas de fallback local 384 dims —
              les dimensions sont incompatibles et corromprait la collection 1536).
            → L'appelant décide : skip insertion ou fallback PG.

        Mode local (pas de openai_api_key) :
            → embed local 384 dims (sentence-transformers).
            → Si local échoue : RuntimeError propagé → fallback PG dans l'appelant.
        """
        if self.s.openai_api_key:
            try:
                return await self._openai_embed(text)
            except Exception as e:
                log.warning(
                    "openai_embed_failed_no_local_fallback",
                    err=str(e)[:80],
                    reason="dimension_incompatibility_384_vs_1536",
                )
                return None  # Pas de fallback local — dimensions incompatibles
        return await self._local_embed(text)

    async def _openai_embed(self, text: str) -> list[float]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.s.openai_api_key)
        resp   = await client.embeddings.create(
            model="text-embedding-3-small", input=text[:8000],
        )
        return resp.data[0].embedding  # 1536 dims

    async def _local_embed(self, text: str) -> list[float]:
        """
        Embedding local via sentence-transformers (all-MiniLM-L6-v2, 384 dims).

        Gestion d'erreurs :
        - sentence-transformers non installé → RuntimeError explicite
        - pas de réseau au premier chargement → RuntimeError avec hint
        - modèle déjà en cache disque (~/.cache/huggingface/) → pas de réseau requis
        - chargement via run_in_executor → ne bloque pas la boucle asyncio
        """
        model_name = _LOCAL_MODEL_NAME

        # Ne pas retenter si déjà échoué dans ce process
        if model_name in _LOCAL_MODEL_FAILED:
            raise RuntimeError(
                f"Modèle local '{model_name}' indisponible (échec précédent). "
                "Définir OPENAI_API_KEY ou vérifier la connexion réseau."
            )

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log.warning("sentence_transformers_missing", hint="pip install sentence-transformers")
            raise RuntimeError(
                "sentence-transformers non installé. "
                "pip install sentence-transformers  ou  définir OPENAI_API_KEY."
            )

        if model_name not in _LOCAL_MODEL_CACHE:
            log.info("local_embed_model_loading", model=model_name)
            try:
                # Chargement non-bloquant avec timeout (120s = suffisant pour ~80MB)
                loop  = asyncio.get_running_loop()
                model = await asyncio.wait_for(
                    loop.run_in_executor(None, SentenceTransformer, model_name),
                    timeout=120.0,
                )
                _LOCAL_MODEL_CACHE[model_name] = model
                log.info("local_embed_model_ready", model=model_name, dim=_LOCAL_VECTOR_DIM)
            except asyncio.TimeoutError:
                _LOCAL_MODEL_FAILED.add(model_name)
                raise RuntimeError(
                    f"Timeout (120s) au chargement du modèle '{model_name}'. "
                    "Première utilisation = téléchargement ~80MB requis. "
                    "Définir OPENAI_API_KEY pour éviter ce problème."
                )
            except OSError as e:
                _LOCAL_MODEL_FAILED.add(model_name)
                log.warning("local_embed_network_error", err=str(e))
                raise RuntimeError(
                    f"Impossible de charger '{model_name}' (réseau/disque : {e}). "
                    "Définir OPENAI_API_KEY ou vérifier la connexion réseau."
                )
            except Exception as e:
                _LOCAL_MODEL_FAILED.add(model_name)
                raise RuntimeError(f"Chargement modèle '{model_name}' échoué : {e}")

        model = _LOCAL_MODEL_CACHE[model_name]
        loop  = asyncio.get_running_loop()
        # encode() est synchrone et CPU-bound → run_in_executor pour ne pas bloquer
        vec   = list(await loop.run_in_executor(None, model.encode, text))

        # Dimension correcte pour all-MiniLM-L6-v2 : 384 dims
        # PAS de padding vers 1536 (fausserait les scores cosine Qdrant)
        return vec[:_LOCAL_VECTOR_DIM]

    # ── PostgreSQL fallback ───────────────────────────────────

    async def _get_pg_pool(self):
        """
        Pool asyncpg partagé — créé une seule fois, réutilisé à chaque appel.
        Remplace les connexions jetables précédentes (perf ×5-10 sous charge).
        min_size=1, max_size=5 : adapté à un système mono-utilisateur.
        """
        if self._pg_pool is not None:
            return self._pg_pool
        try:
            import asyncpg
            dsn = self.s.pg_dsn.replace("+asyncpg", "")
            self._pg_pool = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=5,
                command_timeout=10,
            )
            log.info("pg_pool_created", min=1, max=5)
            return self._pg_pool
        except Exception as e:
            log.warning("pg_pool_creation_failed", err=str(e))
            return None

    async def _pg_store(self, key: str, text: str, tags: list[str]):
        try:
            pool = await self._get_pg_pool()
            if pool is None:
                return
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO vault_memory (key, value, tags)
                       VALUES ($1,$2,$3)
                       ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()""",
                    key, text, tags,
                )
        except Exception as e:
            log.warning("pg_store_failed", err=str(e))

    async def _pg_search(self, query: str, k: int) -> list[str]:
        try:
            pool = await self._get_pg_pool()
            if pool is None:
                return []
            async with pool.acquire() as conn:
                words   = query.split()[:3]
                pattern = f"%{words[0]}%" if words else "%"
                rows    = await conn.fetch(
                    "SELECT value FROM vault_memory WHERE value ILIKE $1 LIMIT $2",
                    pattern, k,
                )
            return [r["value"] for r in rows]
        except Exception as e:
            log.warning("pg_search_failed", err=str(e))
            return []

    async def close(self) -> None:
        """Ferme proprement le pool PostgreSQL (appelé au shutdown du bot)."""
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None
            log.info("pg_pool_closed")
