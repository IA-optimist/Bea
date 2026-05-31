import structlog
log = structlog.get_logger(__name__)
"""
continual_memory.py — Replay buffer intelligent pour JarvisMax
Résout l'oubli catastrophique entre sessions via prioritized experience replay.

Stratégie :
  - Store: upsert dans Qdrant avec embedding du goal
  - Replay: score combiné = 0.6 * cosine_sim + 0.4 * surprise_score
  - Consolidate: LLM summarize des patterns récents
  - Surprise: 1 - cosine_similarity(embed(expected), embed(actual))
"""

from dataclasses import dataclass, field
import asyncio
import json
import hashlib
import time
import uuid
import requests
import numpy as np

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:  # structlog not installed (smoke env)
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Experience:
    mission_id: str
    goal: str
    result: str
    surprise_score: float  # 0-1
    success: bool
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core module
# ---------------------------------------------------------------------------

class ContinualMemory:
    """
    Replay buffer intelligent : stocke et rejoue les expériences importantes
    pour éviter l'oubli catastrophique entre les sessions.

    Stratégie : prioritized replay = favorise les expériences surprenantes + récentes
    """

    def __init__(
        self,
        qdrant_url: str = "http://qdrant:6333",
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "nomic-embed-text",
        llm_model: str = "llama3",
    ):
        self.qdrant_url = qdrant_url
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.llm_model = llm_model
        self.collection = "jarvis_continual_memory"
        self._embed_dim = 768  # nomic-embed-text outputs 768; fallback is 384
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> list[float]:
        """Embedding via Ollama nomic-embed-text, fallback to hash-based vector."""
        try:
            r = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.ollama_model, "prompt": text[:500]},
                timeout=10,
            )
            r.raise_for_status()
            vec = r.json()["embedding"]
            # Update dim on first successful call
            if len(vec) != self._embed_dim:
                self._embed_dim = len(vec)
            return vec
        except Exception:
            return self._hash_embed(text)

    def _hash_embed(self, text: str, dim: int = 768) -> list[float]:
        """Deterministic hash-based fallback embedding (768-dimensional)."""
        h = hashlib.sha256(text.encode()).digest()
        vec = [(b / 255.0) * 2 - 1 for b in h]  # 32 values
        # Tile to requested dim
        repetitions = (dim // len(vec)) + 1
        vec = (vec * repetitions)[:dim]
        return vec

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it doesn't exist yet."""
        try:
            r = requests.get(
                f"{self.qdrant_url}/collections/{self.collection}", timeout=5
            )
            if r.status_code == 404:
                # Try to infer dim from a test embed
                test_vec = self._embed("test")
                dim = len(test_vec)
                requests.put(
                    f"{self.qdrant_url}/collections/{self.collection}",
                    json={"vectors": {"size": dim, "distance": "Cosine"}},
                    timeout=10,
                )
        except Exception:
            pass  # Qdrant unavailable at init — store_experience will handle

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))

    def _point_id(self, mission_id: str) -> str:
        """Generate a stable UUID from mission_id (Qdrant needs UUID or uint)."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, mission_id))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def store_experience(
        self,
        mission_id: str,
        goal: str,
        result: str,
        surprise_score: float,
        success: bool,
        tags: list[str] = None,
    ) -> None:
        """
        Stocke une expérience dans le replay buffer Qdrant.
        Upsert : si mission_id existe déjà, il est mis à jour.
        """
        tags = tags or []
        loop = asyncio.get_event_loop()

        # Embed in thread pool to avoid blocking the event loop
        vector = await loop.run_in_executor(None, self._embed, goal)

        payload = {
            "mission_id": mission_id,
            "goal": goal,
            "result": result[:500],
            "surprise_score": float(surprise_score),
            "success": bool(success),
            "timestamp": time.time(),
            "tags": tags,
        }

        point = {
            "id": self._point_id(mission_id),
            "vector": vector,
            "payload": payload,
        }

        def _upsert():
            return requests.put(
                f"{self.qdrant_url}/collections/{self.collection}/points",
                json={"points": [point]},
                timeout=15,
            )

        try:
            resp = await loop.run_in_executor(None, _upsert)
            resp.raise_for_status()
        except Exception as e:
            # Non-fatal: log and continue
            log.warning("continual_memory.store_experience_failed", err=str(e)[:200])

    async def get_replay_batch(
        self, current_goal: str, n: int = 5
    ) -> list[Experience]:
        """
        Sélectionne les N expériences les plus pertinentes + surprenantes.

        Score combiné = 0.6 * cosine_similarity + 0.4 * surprise_score

        Qdrant retourne déjà les vecteurs triés par cosine_sim.
        On re-trie ensuite avec le score boosté.
        """
        loop = asyncio.get_event_loop()
        query_vec = await loop.run_in_executor(None, self._embed, current_goal)

        # Retrieve more candidates than needed so we can re-rank
        candidates = min(n * 4, 50)

        def _search():
            return requests.post(
                f"{self.qdrant_url}/collections/{self.collection}/points/search",
                json={
                    "vector": query_vec,
                    "limit": candidates,
                    "with_payload": True,
                    "with_vector": False,
                },
                timeout=10,
            )

        try:
            resp = await loop.run_in_executor(None, _search)
            resp.raise_for_status()
            hits = resp.json().get("result", [])
        except Exception as e:
            log.warning("continual_memory.get_replay_batch_failed", err=str(e)[:200])
            return []

        # Re-rank with boosted score
        ranked = []
        for hit in hits:
            cosine_sim = float(hit.get("score", 0.0))  # already in [0,1] for cosine
            p = hit["payload"]
            surprise = float(p.get("surprise_score", 0.0))
            boosted = 0.6 * cosine_sim + 0.4 * surprise
            ranked.append((boosted, p))

        ranked.sort(key=lambda x: x[0], reverse=True)

        experiences = []
        for _, p in ranked[:n]:
            experiences.append(
                Experience(
                    mission_id=p.get("mission_id", "unknown"),
                    goal=p.get("goal", ""),
                    result=p.get("result", ""),
                    surprise_score=p.get("surprise_score", 0.0),
                    success=p.get("success", False),
                    timestamp=p.get("timestamp", 0.0),
                    tags=p.get("tags", []),
                )
            )

        return experiences

    async def consolidate(self) -> dict:
        """
        Résume les patterns appris récemment (30 derniers jours).
        Retourne un dict avec lessons apprises et patterns récurrents.
        """
        loop = asyncio.get_event_loop()
        cutoff = time.time() - 30 * 86400  # 30 days ago

        # Scroll all points (paginate with offset)
        all_payloads = []
        offset = None

        def _scroll(offset_val):
            body = {
                "limit": 100,
                "with_payload": True,
                "with_vector": False,
                "filter": {
                    "must": [
                        {
                            "key": "timestamp",
                            "range": {"gte": cutoff},
                        }
                    ]
                },
            }
            if offset_val is not None:
                body["offset"] = offset_val
            return requests.post(
                f"{self.qdrant_url}/collections/{self.collection}/points/scroll",
                json=body,
                timeout=15,
            )

        try:
            while True:
                resp = await loop.run_in_executor(None, _scroll, offset)
                resp.raise_for_status()
                data = resp.json().get("result", {})
                points = data.get("points", [])
                for pt in points:
                    all_payloads.append(pt["payload"])
                next_offset = data.get("next_page_offset")
                if not next_offset or not points:
                    break
                offset = next_offset
        except Exception as e:
            log.warning("continual_memory.consolidate_scroll_failed", err=str(e)[:200])
            return {"error": str(e), "lessons": [], "patterns": []}

        if not all_payloads:
            return {"lessons": [], "patterns": [], "total_experiences": 0}

        # Build summary text for LLM
        success_count = sum(1 for p in all_payloads if p.get("success"))
        fail_count = len(all_payloads) - success_count

        # Sample up to 20 experiences for LLM context
        sample = all_payloads[:20]
        exp_lines = []
        for p in sample:
            status = "✅" if p.get("success") else "❌"
            exp_lines.append(
                f"{status} [{', '.join(p.get('tags', []))}] {p.get('goal','')[:80]} → {p.get('result','')[:100]}"
            )
        exp_text = "\n".join(exp_lines)

        prompt = (
            f"Tu es un assistant IA qui analyse des expériences de missions passées.\n"
            f"Voici {len(all_payloads)} expériences récentes (30 jours) — {success_count} succès, {fail_count} échecs.\n\n"
            f"Échantillon :\n{exp_text}\n\n"
            f"Identifie :\n"
            f"1. Les 3 leçons les plus importantes à retenir\n"
            f"2. Les patterns récurrents (succès ou échec)\n"
            f"3. Les domaines où l'amélioration est la plus visible\n"
            f"Réponds en JSON : {{\"lessons\": [...], \"patterns\": [...], \"improving_domains\": [...]}}"
        )

        def _llm_call():
            return requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=60,
            )

        try:
            llm_resp = await loop.run_in_executor(None, _llm_call)
            llm_resp.raise_for_status()
            raw = llm_resp.json().get("response", "{}")
            summary = json.loads(raw)
        except Exception as e:
            log.warning("continual_memory.consolidate_llm_failed", err=str(e)[:200])
            summary = {
                "lessons": ["LLM unavailable — check Ollama connection"],
                "patterns": [],
                "improving_domains": [],
            }

        summary["total_experiences"] = len(all_payloads)
        summary["success_rate"] = round(success_count / len(all_payloads), 3) if all_payloads else 0.0
        return summary

    def compute_surprise(self, expected: str, actual: str) -> float:
        """
        Mesure à quel point le résultat était inattendu.
        Score = 1 - cosine_similarity(embed(expected), embed(actual))
        Retourne un float dans [0, 1] : 0 = pas de surprise, 1 = totalement inattendu.
        """
        vec_expected = self._embed(expected)
        vec_actual = self._embed(actual)
        sim = self._cosine_similarity(vec_expected, vec_actual)
        # Cosine similarity in [-1, 1]; clamp to [0, 1] then invert
        sim_clamped = max(0.0, min(1.0, (sim + 1.0) / 2.0))
        return round(1.0 - sim_clamped, 4)

    def build_context_injection(self, experiences: list[Experience]) -> str:
        """Formate les expériences pour injection dans le prompt."""
        if not experiences:
            return ""
        lines = ["## Expériences passées pertinentes :"]
        for exp in experiences:
            status = "✅" if exp.success else "❌"
            lines.append(
                f"{status} {exp.goal[:80]} → {exp.result[:100]} (surprise: {exp.surprise_score:.2f})"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick smoke-test (run directly: python continual_memory.py)
# ---------------------------------------------------------------------------

async def _smoke_test():
    print("=== ContinualMemory Smoke Test ===")
    cm = ContinualMemory()

    # Store a few experiences
    await cm.store_experience(
        mission_id="m001",
        goal="Écrire une fonction Python qui trie une liste",
        result="Fonction sorted() utilisée, retourne liste triée en O(n log n)",
        surprise_score=0.1,
        success=True,
        tags=["python", "algorithmique"],
    )
    await cm.store_experience(
        mission_id="m002",
        goal="Résoudre une équation différentielle du second ordre",
        result="Méthode de Runge-Kutta 4 appliquée, convergence en 0.001",
        surprise_score=0.7,
        success=True,
        tags=["maths", "numérique"],
    )
    await cm.store_experience(
        mission_id="m003",
        goal="Analyser un contrat de bail commercial",
        result="Clauses abusives détectées en section 4.2, recommandation avocat",
        surprise_score=0.5,
        success=False,
        tags=["juridique", "analyse"],
    )

    print("\n[store_experience] 3 expériences stockées")

    # Retrieve replay batch
    batch = await cm.get_replay_batch("Écrire du code Python pour manipuler des listes", n=2)
    print(f"\n[get_replay_batch] {len(batch)} expériences récupérées:")
    for exp in batch:
        print(f"  - {exp.goal[:60]} (surprise={exp.surprise_score})")

    # Context injection
    ctx = cm.build_context_injection(batch)
    print(f"\n[build_context_injection]:\n{ctx}")

    # Compute surprise
    surprise = cm.compute_surprise(
        "La fonction va retourner True",
        "La fonction a levé une exception TypeError"
    )
    print(f"\n[compute_surprise]: {surprise:.4f}")

    # Consolidate
    summary = await cm.consolidate()
    print(f"\n[consolidate]: {json.dumps(summary, ensure_ascii=False, indent=2)}")

    print("\n=== Smoke Test DONE ===")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
