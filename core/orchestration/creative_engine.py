"""
creative_engine.py — JarvisMax Creative Engine
================================================
Module de créativité structurée pour JarvisMax.
Objectif : sortir de la recomposition pour aller vers l'invention.

Architecture :
  - CreativeEngine       : diversité structurée + analogies cross-domaines
  - CrossMissionConnector: connexions entre missions passées (via embeddings)
  - ArtificialCuriosity  : détection de surprises et génération de questions
  - CreativityTests      : métriques pour mesurer si on invente vraiment

Usage :
  engine = CreativeEngine(llm_client=..., mode="creative")
  solutions = await engine.generate_diverse("Optimiser le cache Redis", n=5)
  best = await engine.select_best(solutions, criteria={"novelty": 0.6, "feasibility": 0.4})
"""

from __future__ import annotations
from abc import ABC, abstractmethod

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────

@dataclass
class Solution:
    id: str
    content: str
    domain_origin: str          # domaine d'où vient l'idée ("biology", "architecture", "direct")
    surprise_score: float = 0.0 # [0,1] — 0=prévisible, 1=totalement inattendu
    feasibility: float = 0.0    # [0,1]
    novelty_hash: str = ""      # hash pour détecter les doublons cross-missions
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.novelty_hash:
            self.novelty_hash = hashlib.sha256(
                self.content[:200].encode()
            ).hexdigest()[:16]


@dataclass
class Analogy:
    source_domain: str
    target_domain: str
    source_concept: str
    target_concept: str
    explanation: str
    strength: float  # [0,1]


@dataclass
class Surprise:
    mission_id: str
    expected: str
    observed: str
    delta_description: str
    questions: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ─────────────────────────────────────────────
# LLM Client interface (adaptateur)
# ─────────────────────────────────────────────

class LLMClient(ABC):
    """
    Interface minimale. Implémentez pour votre backend (OpenRouter, Ollama, etc.)
    Exemple d'implémentation pour OpenRouter disponible dans jarvis_core/llm/openrouter.py
    """
    @abstractmethod
    async def complete(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        raise NotImplementedError

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    """
    Adaptateur Ollama pour CreativeEngine.
    Utilisé quand ollama_url est passé directement aux classes du pipeline.
    Modèle par défaut : llama3 (si disponible), sinon le premier modèle Ollama trouvé.
    """

    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = ollama_url.rstrip("/")
        self.model = model

    async def complete(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        import urllib.request
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                data = json.loads(resp.read().decode())
                return data.get("response", "").strip()
        except Exception as e:
            logger.warning(f"OllamaLLMClient.complete error: {e}")
            return ""

    async def embed(self, text: str) -> list[float]:
        import urllib.request
        payload = json.dumps({"model": self.model, "prompt": text}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                data = json.loads(resp.read().decode())
                return data.get("embedding", [])
        except Exception as e:
            logger.warning(f"OllamaLLMClient.embed error: {e}")
            return []


# ─────────────────────────────────────────────
# 1. CREATIVE ENGINE — Diversité structurée
# ─────────────────────────────────────────────

ANALOGY_DOMAINS = [
    "evolutionary biology",
    "urban planning",
    "jazz improvisation",
    "thermodynamics",
    "military strategy",
    "mycorrhizal networks",
    "origami",
    "epidemiology",
    "materials science",
    "game theory",
]

REFRAME_TEMPLATES = [
    "How would a {domain} expert solve this? Problem: {problem}",
    "If this problem existed in {domain}, what would the solution look like? Problem: {problem}",
    "What metaphor from {domain} best captures this problem, and what does it suggest? Problem: {problem}",
]


class CreativeEngine:
    """
    Moteur de créativité structurée pour JarvisMax.

    mode="creative"  → active generate_diverse + cross_domain + analogies
    mode="standard"  → retourne une seule solution directe (comportement actuel)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        mode: str = "creative",
        domains: list[str] | None = None,
    ):
        self.llm = llm_client
        self.mode = mode
        self.domains = domains or ANALOGY_DOMAINS[:5]

    async def generate_diverse(self, problem: str, n: int = 5) -> list[Solution]:
        """
        Génère N solutions structurellement différentes en utilisant :
        1. Une solution directe (baseline)
        2. N-1 solutions via analogies cross-domaines

        En mode standard : retourne uniquement la solution directe.
        """
        if self.mode == "standard":
            direct = await self._direct_solution(problem)
            return [direct]

        tasks = [self._direct_solution(problem)]
        selected_domains = self.domains[: max(0, n - 1)]
        tasks += [self._analogical_solution(problem, d) for d in selected_domains]

        solutions = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [s for s in solutions if isinstance(s, Solution)]

        # Scoring de surprise en parallèle
        score_tasks = [self._compute_surprise_score(s) for s in valid]
        scores = await asyncio.gather(*score_tasks, return_exceptions=True)
        for sol, score in zip(valid, scores):
            if isinstance(score, float):
                sol.surprise_score = score

        return valid

    async def _direct_solution(self, problem: str) -> Solution:
        prompt = (
            f"Solve this problem directly and concisely.\n\n"
            f"Problem: {problem}\n\n"
            f"Solution:"
        )
        content = await self.llm.complete(prompt, temperature=0.3)
        return Solution(
            id=f"direct_{int(time.time()*1000)}",
            content=content.strip(),
            domain_origin="direct",
        )

    async def _analogical_solution(self, problem: str, domain: str) -> Solution:
        prompt = (
            f"You are an expert in {domain}. "
            f"Reframe the following problem as if it were a challenge in your field, "
            f"then solve it using concepts and methods from {domain}. "
            f"Finally, translate the solution back to the original context.\n\n"
            f"Problem: {problem}\n\n"
            f"Step 1 – Reframe in {domain}:\n"
            f"Step 2 – Solution in {domain}:\n"
            f"Step 3 – Translation back:\n"
        )
        content = await self.llm.complete(prompt, temperature=0.8)
        return Solution(
            id=f"{domain.replace(' ', '_')}_{int(time.time()*1000)}",
            content=content.strip(),
            domain_origin=domain,
        )

    async def cross_domain_connect(
        self, concept: str, domains: list[str]
    ) -> list[Analogy]:
        """
        Trouve des analogies entre un concept et plusieurs domaines.
        Utile pour découvrir des insights inattendus avant de résoudre.
        """
        tasks = [self._find_analogy(concept, d) for d in domains]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, Analogy)]

    async def _find_analogy(self, concept: str, target_domain: str) -> Analogy:
        prompt = (
            f"Find a deep analogy between '{concept}' and something in {target_domain}.\n"
            f"Return JSON with keys: source_concept, target_concept, explanation, strength (0-1).\n"
            f"JSON only, no extra text."
        )
        raw = await self.llm.complete(prompt, temperature=0.7, max_tokens=300)
        try:
            data = json.loads(raw.strip())
            return Analogy(
                source_domain="original",
                target_domain=target_domain,
                source_concept=data.get("source_concept", concept),
                target_concept=data.get("target_concept", ""),
                explanation=data.get("explanation", ""),
                strength=float(data.get("strength", 0.5)),
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Analogy parse error for {target_domain}: {e}")
            return Analogy(
                source_domain="original",
                target_domain=target_domain,
                source_concept=concept,
                target_concept="(parse error)",
                explanation=raw[:200],
                strength=0.3,
            )

    async def reframe_problem(self, problem: str) -> list[str]:
        """
        Reformule le problème dans 3 domaines différents.
        Chaque reformulation peut révéler une structure cachée du problème.
        """
        import random
        # Bandit B311 nosec: creative reframing diversity, not security.
        # The random output is fed to LLM prompts; no token / secret value
        # is derived from it.
        selected = random.sample(self.domains, min(3, len(self.domains)))  # nosec B311
        tasks = []
        for domain in selected:
            template = random.choice(REFRAME_TEMPLATES)  # nosec B311
            prompt = template.format(domain=domain, problem=problem)
            tasks.append(self.llm.complete(prompt, temperature=0.8, max_tokens=200))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r.strip() for r in results if isinstance(r, str) and r.strip()]

    async def select_best(
        self, solutions: list[Solution], criteria: dict
    ) -> Solution:
        """
        Sélectionne la meilleure solution selon des critères pondérés.

        criteria exemple : {"novelty": 0.6, "feasibility": 0.4}

        novelty  → repose sur surprise_score
        feasibility → repose sur feasibility (à scorer via LLM si nécessaire)
        """
        if not solutions:
            raise ValueError("No solutions to select from")

        if len(solutions) == 1:
            return solutions[0]

        # Score composite
        scored = []
        for sol in solutions:
            score = (
                criteria.get("novelty", 0.5) * sol.surprise_score
                + criteria.get("feasibility", 0.5) * sol.feasibility
            )
            scored.append((score, sol))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    async def surprise_score(self, solution: str) -> float:
        """
        Évalue à quel point une solution est inattendue.
        Score [0,1] : 0 = prévisible, 1 = totalement inattendu.
        Proxy : l'LLM juge si la solution est conventionnelle ou originale.
        """
        return await self._compute_surprise_score_from_text(solution)

    async def _compute_surprise_score(self, solution: Solution) -> float:
        return await self._compute_surprise_score_from_text(solution.content)

    async def _compute_surprise_score_from_text(self, text: str) -> float:
        prompt = (
            f"Rate how surprising/unexpected this solution is on a scale from 0 to 1.\n"
            f"0 = completely conventional and expected\n"
            f"1 = highly unexpected, novel approach that most wouldn't think of\n\n"
            f"Solution: {text[:500]}\n\n"
            f"Return only a number between 0 and 1. Nothing else."
        )
        try:
            raw = await self.llm.complete(prompt, temperature=0.1, max_tokens=10)
            return max(0.0, min(1.0, float(raw.strip())))
        except (ValueError, TypeError):
            return 0.5  # valeur neutre si parsing échoue


# ─────────────────────────────────────────────
# 2. CROSS-MISSION CONNECTOR
# ─────────────────────────────────────────────

class MissionStore(ABC):
    """
    Interface vers le store de missions (à implémenter avec Qdrant/pgvector).
    Contrat minimal pour CrossMissionConnector.
    """
    @abstractmethod
    def get_mission(self, mission_id: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def search_by_embedding(
        self, embedding: list[float], top_k: int
    ) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_all_missions(self) -> list[dict]:
        raise NotImplementedError


class CrossMissionConnector:
    """
    Trouve des connexions entre missions en apparence non liées.
    Requiert un store vectoriel (Qdrant recommandé — déjà dans la stack JarvisMax).

    Architecture :
      1. Chaque mission est indexée avec son embedding + pattern abstrait
      2. find_analogies → recherche vectorielle dans l'espace des patterns
      3. suggest_cross_application → l'LLM génère l'insight de transfert
    """

    def __init__(self, llm_client: LLMClient, mission_store: MissionStore):
        self.llm = llm_client
        self.store = mission_store

    def find_analogies(self, mission_id: str, top_k: int = 5) -> list[Analogy]:
        """
        Trouve les missions les plus analogues (structurellement, pas thématiquement).
        Utilise l'embedding du pattern abstrait, pas du contenu textuel brut.
        """
        mission = self.store.get_mission(mission_id)
        if not mission:
            logger.warning(f"Mission {mission_id} not found")
            return []

        pattern = mission.get("abstract_pattern", mission.get("summary", ""))
        if not pattern:
            return []

        # Note: embed() est async — dans un contexte sync, utiliser asyncio.run()
        # ou adapter selon le contexte d'appel
        import asyncio
        loop = asyncio.get_event_loop()
        embedding = loop.run_until_complete(self.llm.embed(pattern))

        similar = self.store.search_by_embedding(embedding, top_k=top_k + 1)
        # Exclure la mission elle-même
        similar = [m for m in similar if m.get("id") != mission_id][:top_k]

        analogies = []
        for m in similar:
            analogies.append(Analogy(
                source_domain=mission.get("domain", "unknown"),
                target_domain=m.get("domain", "unknown"),
                source_concept=pattern[:100],
                target_concept=m.get("abstract_pattern", m.get("summary", ""))[:100],
                explanation=f"Structural similarity between mission {mission_id} and {m.get('id')}",
                strength=m.get("score", 0.5),
            ))

        return analogies

    def extract_abstract_pattern(self, mission_id: str) -> str:
        """
        Extrait le pattern abstrait d'une mission : ce qu'elle fait structurellement,
        indépendamment du domaine.

        Exemple :
          Mission "optimiser Redis" → "Reduce bottleneck in high-frequency access system"
          Mission "améliorer communication équipe" → "Reduce bottleneck in high-frequency access system"
          → Même pattern → insight cross-domaine possible
        """
        mission = self.store.get_mission(mission_id)
        if not mission:
            return ""

        cached = mission.get("abstract_pattern")
        if cached:
            return cached

        # Génère le pattern via LLM si absent
        import asyncio
        loop = asyncio.get_event_loop()
        summary = mission.get("summary", mission.get("description", ""))
        prompt = (
            f"Extract the abstract structural pattern of this task. "
            f"Describe what it does at a conceptual level, without any domain-specific terms. "
            f"Be concise (1-2 sentences).\n\n"
            f"Task: {summary}\n\nAbstract pattern:"
        )
        pattern = loop.run_until_complete(
            self.llm.complete(prompt, temperature=0.3, max_tokens=100)
        )
        return pattern.strip()

    def suggest_cross_application(self, pattern: str, new_context: str) -> str:
        """
        Suggère comment un pattern abstrait (extrait d'une mission passée)
        pourrait s'appliquer à un nouveau contexte.
        """
        import asyncio
        loop = asyncio.get_event_loop()
        prompt = (
            f"We discovered this abstract pattern from past experience:\n"
            f"Pattern: {pattern}\n\n"
            f"New context: {new_context}\n\n"
            f"How could this pattern be applied to the new context? "
            f"Give a concrete, actionable suggestion."
        )
        result = loop.run_until_complete(
            self.llm.complete(prompt, temperature=0.6, max_tokens=300)
        )
        return result.strip()


# ─────────────────────────────────────────────
# 3. ARTIFICIAL CURIOSITY
# ─────────────────────────────────────────────

class ArtificialCuriosity:
    """
    Détecte les surprises dans les résultats de missions et gère des questions.

    Intégration dans le pipeline :
      curiosity = ArtificialCuriosity(llm_client)
      surprise = await curiosity.detect_surprise(mission_id, expected, observed)
      if surprise.questions:
          # Sauvegarder pour exploration future
          await save_surprise_to_store(surprise)

    Ou avec ollama_url (convenience) :
      curiosity = ArtificialCuriosity(ollama_url="http://localhost:11434")
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        surprise_threshold: float = 0.6,
        ollama_url: str | None = None,
    ):
        if llm_client is None and ollama_url is not None:
            llm_client = OllamaLLMClient(ollama_url=ollama_url)
        elif llm_client is None:
            llm_client = OllamaLLMClient()  # default localhost
        self.llm = llm_client
        self.threshold = surprise_threshold
        self._surprise_log: list[Surprise] = []

    async def detect_surprise(
        self,
        mission_id: str,
        expected: str,
        observed: str,
    ) -> Surprise | None:
        """
        Compare l'attendu et l'observé. Si écart significatif, génère une Surprise.
        Retourne None si pas de surprise détectée (sous le seuil).
        """
        prompt = (
            f"Compare these two outcomes:\n"
            f"Expected: {expected}\n"
            f"Observed: {observed}\n\n"
            f"On a scale 0-1, how surprising is the difference? "
            f"Return JSON: {{\"score\": 0.x, \"delta\": \"brief description of the gap\"}}"
        )
        try:
            raw = await self.llm.complete(prompt, temperature=0.2, max_tokens=150)
            data = json.loads(raw.strip())
            score = float(data.get("score", 0))
            delta = data.get("delta", "")
        except (json.JSONDecodeError, ValueError):
            return None

        if score < self.threshold:
            return None

        questions = await self._generate_questions(expected, observed, delta)

        surprise = Surprise(
            mission_id=mission_id,
            expected=expected,
            observed=observed,
            delta_description=delta,
            questions=questions,
        )
        self._surprise_log.append(surprise)
        logger.info(f"[Curiosity] Surprise detected in {mission_id}: score={score:.2f}")
        return surprise

    async def _generate_questions(
        self, expected: str, observed: str, delta: str
    ) -> list[str]:
        """
        Génère 3 questions à partir d'une surprise.
        Ces questions alimentent l'exploration future.
        """
        prompt = (
            f"A surprising result occurred:\n"
            f"Expected: {expected}\n"
            f"Observed: {observed}\n"
            f"Gap: {delta}\n\n"
            f"Generate exactly 3 investigative questions that would help understand why this happened. "
            f"Each question on its own line. No numbering."
        )
        raw = await self.llm.complete(prompt, temperature=0.7, max_tokens=200)
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        return lines[:3]

    def get_open_questions(self) -> list[str]:
        """Retourne toutes les questions ouvertes générées par des surprises."""
        questions = []
        for surprise in self._surprise_log:
            questions.extend(surprise.questions)
        return questions

    def get_surprise_log(self) -> list[Surprise]:
        return list(self._surprise_log)

    def compute_surprise_score(self, goal: str, result: str) -> float:
        """
        Convenience sync wrapper : évalue le score de surprise entre goal et result.
        Utilise l'LLM pour estimer l'écart attendu vs observé.
        Retourne [0.0, 1.0] — 0 = prévisible, 1 = inattendu.
        Fail-safe : retourne 0.0 si LLM indisponible.
        """
        import asyncio
        prompt = (
            f"Compare this goal and its result:\n"
            f"Goal: {goal[:300]}\n"
            f"Result: {result[:300]}\n\n"
            f"On a scale 0-1, how surprising or unexpected is this result given the goal? "
            f"0 = result is exactly what was expected, 1 = completely unexpected.\n"
            f"Return only a number between 0 and 1. Nothing else."
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return 0.0  # cannot block running loop
            raw = loop.run_until_complete(
                self.llm.complete(prompt, temperature=0.1, max_tokens=10)
            )
            return max(0.0, min(1.0, float(raw.strip())))
        except Exception:
            return 0.0

    async def generate_curiosity_questions(
        self, goal: str, result: str
    ) -> list[str]:
        """
        Génère des questions d'exploration à partir d'un goal et d'un résultat.
        Utilisé quand compute_surprise_score détecte une anomalie (> threshold).
        """
        return await self._generate_questions(
            expected=f"Result expected from: {goal[:200]}",
            observed=result[:300],
            delta="Detected as surprising by compute_surprise_score",
        )


# ─────────────────────────────────────────────
# 4. CREATIVITY TESTS
# ─────────────────────────────────────────────

class CreativityTests:
    """
    3 tests pour mesurer objectivement si le moteur créatif produit de la valeur.

    Ces tests sont conçus pour être exécutés en dehors du pipeline principal,
    comme des benchmarks périodiques.
    """

    def __init__(self, llm_client: LLMClient, mission_store: MissionStore):
        self.llm = llm_client
        self.store = mission_store

    async def test_ab_diversity(
        self,
        problem: str,
        standard_solution: str,
        creative_solution: str,
    ) -> dict:
        """
        Test A/B : demande à l'LLM (proxy du jugement humain) laquelle est
        plus originale et potentiellement plus utile.

        En production : remplacer par vrai jugement humain via UI.
        """
        prompt = (
            f"Problem: {problem}\n\n"
            f"Solution A (standard): {standard_solution}\n\n"
            f"Solution B (creative): {creative_solution}\n\n"
            f"Which solution is more original and potentially more insightful? "
            f"Return JSON: {{\"winner\": \"A\" or \"B\", \"reason\": \"...\", \"originality_A\": 0.x, \"originality_B\": 0.x}}"
        )
        raw = await self.llm.complete(prompt, temperature=0.3, max_tokens=200)
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            return {"winner": "unknown", "reason": raw[:200]}

    def test_novelty(self, solution: Solution) -> dict:
        """
        Test de nouveauté : vérifie si la solution a déjà été proposée dans
        les missions passées (via hash + recherche vectorielle).

        Retourne : {"is_novel": bool, "similar_mission_ids": list[str]}
        """
        all_missions = self.store.get_all_missions()

        # Check par hash (exact)
        known_hashes = {
            m.get("solution_hash", "") for m in all_missions
        }
        if solution.novelty_hash in known_hashes:
            return {"is_novel": False, "method": "hash_match", "similar_mission_ids": []}

        # Si on a des embeddings, on pourrait faire une recherche vectorielle ici
        # Pour l'instant : novel par défaut si pas de hash match
        return {
            "is_novel": True,
            "method": "hash_check",
            "similar_mission_ids": [],
            "note": "Vector similarity check requires embedding index"
        }

    async def test_effectiveness(
        self,
        problem: str,
        solution: Solution,
        evaluation_criteria: str = "correctness, completeness, efficiency",
    ) -> dict:
        """
        Test d'efficacité : l'LLM évalue si la solution créative est praticable.
        Note : l'évaluation par LLM a ses limites — préférer tests unitaires quand possible.
        """
        prompt = (
            f"Problem: {problem}\n\n"
            f"Solution: {solution.content}\n\n"
            f"Evaluate this solution on: {evaluation_criteria}.\n"
            f"Return JSON: {{\"score\": 0-10, \"strengths\": [...], \"weaknesses\": [...], \"verdict\": \"viable|risky|not_viable\"}}"
        )
        raw = await self.llm.complete(prompt, temperature=0.2, max_tokens=300)
        try:
            data = json.loads(raw.strip())
            data["domain_origin"] = solution.domain_origin
            data["surprise_score"] = solution.surprise_score
            return data
        except json.JSONDecodeError:
            return {"score": 0, "verdict": "parse_error", "raw": raw[:200]}

    async def run_full_benchmark(
        self,
        problem: str,
        engine: CreativeEngine,
    ) -> dict:
        """
        Lance les 3 tests sur un problème et retourne un rapport complet.
        """
        # Génère une solution standard et des solutions créatives
        standard_engine = CreativeEngine(engine.llm, mode="standard")
        creative_engine = engine

        standard_solutions = await standard_engine.generate_diverse(problem, n=1)
        creative_solutions = await creative_engine.generate_diverse(problem, n=5)

        if not standard_solutions or not creative_solutions:
            return {"error": "Failed to generate solutions"}

        std_sol = standard_solutions[0]
        # Sélectionne la plus surprenante des créatives
        best_creative = max(creative_solutions, key=lambda s: s.surprise_score)

        # Test A/B
        ab_result = await self.test_ab_diversity(
            problem, std_sol.content, best_creative.content
        )

        # Test nouveauté
        novelty_result = self.test_novelty(best_creative)

        # Test efficacité des deux
        std_effectiveness = await self.test_effectiveness(problem, std_sol)
        creative_effectiveness = await self.test_effectiveness(problem, best_creative)

        return {
            "problem": problem,
            "ab_test": ab_result,
            "novelty_test": novelty_result,
            "effectiveness_standard": std_effectiveness,
            "effectiveness_creative": creative_effectiveness,
            "creative_surprise_score": best_creative.surprise_score,
            "creative_domain": best_creative.domain_origin,
        }


# ─────────────────────────────────────────────
# 5. PIPELINE INTEGRATION
# ─────────────────────────────────────────────

class JarvisCreativePipeline:
    """
    Point d'entrée unique pour intégrer le moteur créatif dans JarvisMax.

    mode="creative"  → diversité + analogies + curiosité
    mode="standard"  → comportement actuel inchangé

    Exemple d'usage dans un agent JarvisMax :

        pipeline = JarvisCreativePipeline(llm_client=openrouter_client, mode=task.mode)
        result = await pipeline.run(
            problem=task.description,
            mission_id=task.id,
            expected_outcome=task.expected_outcome,
        )
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        mission_store: MissionStore | None = None,
        mode: str = "creative",
        n_solutions: int = 5,
        selection_criteria: dict | None = None,
        ollama_url: str | None = None,
    ):
        if llm_client is None and ollama_url is not None:
            llm_client = OllamaLLMClient(ollama_url=ollama_url)
        elif llm_client is None:
            llm_client = OllamaLLMClient()  # default localhost
        self.mode = mode
        self.engine = CreativeEngine(llm_client, mode=mode)
        self.curiosity = ArtificialCuriosity(llm_client)
        self.connector = (
            CrossMissionConnector(llm_client, mission_store)
            if mission_store else None
        )
        self.n = n_solutions
        self.criteria = selection_criteria or {"novelty": 0.5, "feasibility": 0.5}

    async def run(
        self,
        problem: str,
        mission_id: str | None = None,
        expected_outcome: str | None = None,
        actual_outcome: str | None = None,
        n_solutions: int | None = None,
    ) -> dict:
        """
        Pipeline complet :
        1. [creative] Reformulations analogiques
        2. Génération de N solutions
        3. Sélection de la meilleure
        4. [creative] Détection de surprises si outcome disponible
        5. [creative] Cross-mission analogies si store disponible

        Retourne un dict avec la solution et les métadonnées créatives.
        """
        result: dict[str, Any] = {"mode": self.mode, "problem": problem}

        # Étape 1 : reformulations (mode créatif seulement)
        if self.mode == "creative":
            reframes = await self.engine.reframe_problem(problem)
            result["reframings"] = reframes

        # Étape 2 : génération diverse
        _n = n_solutions if n_solutions is not None else self.n
        solutions = await self.engine.generate_diverse(problem, n=_n)
        result["solutions_count"] = len(solutions)
        result["solutions"] = [
            {
                "domain": s.domain_origin,
                "surprise_score": s.surprise_score,
                "preview": s.content[:200],
            }
            for s in solutions
        ]

        # Étape 3 : sélection
        best = await self.engine.select_best(solutions, self.criteria)
        result["best_solution"] = {
            "domain": best.domain_origin,
            "surprise_score": best.surprise_score,
            "content": best.content,
            "novelty_hash": best.novelty_hash,
        }
        # Convenience keys for meta_orchestrator integration
        result["best"] = best.content if best.content else None
        result["all_solutions"] = [s.content for s in solutions if s.content]

        # Étape 4 : curiosité (si on a les outcomes)
        if expected_outcome and actual_outcome and mission_id:
            surprise = await self.curiosity.detect_surprise(
                mission_id, expected_outcome, actual_outcome
            )
            if surprise:
                result["surprise"] = {
                    "delta": surprise.delta_description,
                    "questions": surprise.questions,
                }

        # Étape 5 : cross-mission (si store disponible et mode créatif)
        if self.mode == "creative" and self.connector and mission_id:
            analogies = self.connector.find_analogies(mission_id, top_k=3)
            result["cross_mission_analogies"] = [
                {
                    "from_domain": a.source_domain,
                    "to_domain": a.target_domain,
                    "explanation": a.explanation,
                    "strength": a.strength,
                }
                for a in analogies
            ]

        return result


# ─────────────────────────────────────────────
# JARVIS NATIVE ADAPTERS
# Connectent le CreativeEngine aux systèmes JarvisMax existants.
# ─────────────────────────────────────────────

class JarvisLLMClient(LLMClient):
    """
    Adaptateur LLM pour CreativeEngine utilisant OpenRouter (LLMFactory).
    Fallback : OllamaLLMClient si OpenRouter indisponible.
    Embed : EmbeddingProvider (nomic-embed-text via Ollama ou MiniLM local).
    """

    def __init__(self, role: str = "fast"):
        self._role = role
        self._embed_provider = None

    def _get_factory(self):
        from core.llm_factory import LLMFactory
        from config.settings import get_settings
        return LLMFactory(get_settings())

    def _get_embed_provider(self):
        if self._embed_provider is None:
            from memory.embeddings import EmbeddingProvider
            from config.settings import get_settings
            self._embed_provider = EmbeddingProvider(get_settings(), provider="auto")
        return self._embed_provider

    async def complete(self, prompt: str, temperature: float = 0.7, max_tokens: int = 1000) -> str:
        try:
            factory = self._get_factory()
            llm = factory.get(self._role)
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning(f"JarvisLLMClient.complete fallback: {e}")
            # Fallback Ollama
            from config.settings import get_settings
            host = get_settings().ollama_host
            ollama = OllamaLLMClient(ollama_url=host, model="tinyllama")
            return await ollama.complete(prompt, temperature, max_tokens)

    async def embed(self, text: str) -> list[float]:
        try:
            return await self._get_embed_provider().embed(text)
        except Exception as e:
            logger.warning(f"JarvisLLMClient.embed failed: {e}")
            return [0.0] * 768


class JarvisMissionStore(MissionStore):
    """
    Implémentation de MissionStore branchée sur MissionSystem + Qdrant.
    Permet à CrossMissionConnector de chercher des analogies dans les missions passées.
    """

    def __init__(self):
        self._embed_provider = None

    def _get_embed(self):
        if self._embed_provider is None:
            from memory.embeddings import EmbeddingProvider
            from config.settings import get_settings
            self._embed_provider = EmbeddingProvider(get_settings(), provider="auto")
        return self._embed_provider

    def get_mission(self, mission_id: str) -> dict | None:
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            ctx = ms._missions.get(mission_id)
            if ctx is None:
                return None
            return {
                "mission_id": ctx.mission_id,
                "goal": ctx.goal,
                "status": ctx.status.value if hasattr(ctx.status, "value") else str(ctx.status),
                "result": ctx.result or "",
            }
        except Exception:
            return None

    def get_all_missions(self) -> list[dict]:
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            return [
                {
                    "mission_id": ctx.mission_id,
                    "goal": ctx.goal,
                    "result": ctx.result or "",
                }
                for ctx in ms._missions.values()
                if ctx.result
            ]
        except Exception:
            return []

    def search_by_embedding(self, embedding: list[float], top_k: int) -> list[dict]:
        """Search missions by vector similarity via Qdrant."""
        try:
            from qdrant_client import QdrantClient
            from config.settings import get_settings
            s = get_settings()
            client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, https=False)
            results = client.search(
                collection_name="jarvismax_memory_384",
                query_vector=embedding[:384],  # Adapt to collection dims
                limit=top_k,
                with_payload=True,
            )
            return [
                {
                    "mission_id": r.payload.get("key", ""),
                    "goal": r.payload.get("content", "")[:200],
                    "score": r.score,
                }
                for r in results
            ]
        except Exception as e:
            logger.debug(f"search_by_embedding failed: {e}")
            # Fallback: keyword search over in-memory missions
            return self.get_all_missions()[:top_k]
