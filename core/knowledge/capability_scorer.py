"""
capability_scorer — Score de compétence de Jarvis par domaine.

Domaines suivis :
  coding       — génération et modification de code
  api_usage    — appels HTTP, intégrations API
  debugging    — analyse d'erreurs, résolution de bugs
  automation   — scripts, pipelines, déploiements
  planning     — décomposition de missions, planification
  research     — collecte d'information, analyse documentaire

Score 0.0–1.0 par domaine, basé sur :
  - taux de réussite des tâches récentes
  - durée moyenne d'exécution (normalisée)
  - nombre d'erreurs moyen
  - nombre de retries moyen

Persistence : workspace/capability_scores.json
Fail-open : aucune exception ne se propage.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

logger = logging.getLogger("jarvis.knowledge.capability")

_PERSIST_PATH = "workspace/capability_scores.json"

# Domaines reconnus
DOMAINS = ("coding", "api_usage", "debugging", "automation", "planning", "research")

# Mapping task_type → domaine
_TASK_TYPE_TO_DOMAIN: Dict[str, str] = {
    "bug_fix": "debugging",
    "debug_task": "debugging",
    "deploy": "automation",
    "deployment": "automation",
    "analysis": "research",
    "research": "research",
    "coding_task": "coding",
    "code_generation": "coding",
    "saas_creation": "coding",
    "api_call": "api_usage",
    "api_usage": "api_usage",
    "test": "automation",
    "improvement": "coding",
    "ceo_planning": "planning",
    "planning": "planning",
    "cybersecurity": "debugging",
}

# Durée de référence par domaine (secondes) — pour normaliser le score de vitesse
_REFERENCE_DURATION: Dict[str, float] = {
    "coding": 120.0,
    "api_usage": 30.0,
    "debugging": 180.0,
    "automation": 90.0,
    "planning": 60.0,
    "research": 150.0,
}


@dataclass
class DomainScore:
    domain: str
    success_count: int = 0
    failure_count: int = 0
    total_duration_s: float = 0.0
    total_errors: int = 0
    total_retries: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def total_tasks(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 0.5  # prior neutre
        return round(self.success_count / self.total_tasks, 4)

    @property
    def avg_duration_s(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return round(self.total_duration_s / self.total_tasks, 2)

    @property
    def avg_errors(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return round(self.total_errors / self.total_tasks, 2)

    @property
    def avg_retries(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return round(self.total_retries / self.total_tasks, 2)

    def compute_score(self) -> float:
        """
        Score composite 0.0–1.0 :
          40% taux de réussite
          30% vitesse (durée vs référence)
          20% propreté (peu d'erreurs)
          10% fluidité (peu de retries)

        Si aucune tâche connue : 0.5 (prior neutre).
        """
        if self.total_tasks == 0:
            return 0.5

        # Composante réussite (0–1)
        success_component = self.success_rate

        # Composante vitesse (0–1) : 1.0 si durée ≤ référence, décroît sinon
        ref_dur = _REFERENCE_DURATION.get(self.domain, 120.0)
        avg_dur = self.avg_duration_s
        if avg_dur <= 0:
            speed_component = 0.5
        elif avg_dur <= ref_dur:
            speed_component = 1.0
        else:
            speed_component = max(0.0, 1.0 - (avg_dur - ref_dur) / ref_dur)

        # Composante erreurs (0–1) : décroît au-delà de 2 erreurs/tâche
        error_component = max(0.0, 1.0 - self.avg_errors / 4.0)

        # Composante retries (0–1) : décroît au-delà de 2 retries
        retry_component = max(0.0, 1.0 - self.avg_retries / 4.0)

        score = (
            0.40 * success_component
            + 0.30 * speed_component
            + 0.20 * error_component
            + 0.10 * retry_component
        )
        return round(min(1.0, max(0.0, score)), 4)


class CapabilityScorer:
    """
    Gestionnaire des scores de compétence par domaine.
    Persiste dans workspace/capability_scores.json.
    """

    def __init__(self):
        self._scores: Dict[str, DomainScore] = {}
        # Initialiser tous les domaines connus
        for domain in DOMAINS:
            self._scores[domain] = DomainScore(domain=domain)
        self._load_from_disk()

    def update_score(
        self,
        domain: str,
        success: bool,
        duration_s: float = 0.0,
        errors: int = 0,
        retries: int = 0,
    ) -> float:
        """
        Met à jour le score d'un domaine après une tâche.

        Args:
            domain     : domaine à mettre à jour (voir DOMAINS)
            success    : True si la tâche a réussi
            duration_s : durée d'exécution en secondes
            errors     : nombre d'erreurs rencontrées
            retries    : nombre de retries effectués

        Returns:
            Nouveau score du domaine (0.0–1.0)
        """
        try:
            if domain not in self._scores:
                self._scores[domain] = DomainScore(domain=domain)

            ds = self._scores[domain]
            if success:
                ds.success_count += 1
            else:
                ds.failure_count += 1
            ds.total_duration_s += max(0.0, float(duration_s))
            ds.total_errors += max(0, int(errors))
            ds.total_retries += max(0, int(retries))
            ds.last_updated = time.time()

            new_score = ds.compute_score()
            logger.debug(
                f"[CapabilityScorer] domain={domain} score={new_score:.3f} "
                f"tasks={ds.total_tasks} success_rate={ds.success_rate:.2f}"
            )
            self._persist()
            return new_score

        except Exception as exc:
            logger.warning(f"[CapabilityScorer] update_score error: {exc}")
            return 0.5

    def update_from_task_type(
        self,
        task_type: str,
        success: bool,
        duration_s: float = 0.0,
        errors: int = 0,
        retries: int = 0,
    ) -> float:
        """
        Met à jour le score en déduisant le domaine depuis le task_type.
        Utile pour une intégration directe depuis MetaOrchestrator.

        Returns:
            Nouveau score du domaine correspondant (0.5 si domain inconnu)
        """
        domain = _TASK_TYPE_TO_DOMAIN.get(task_type, "")
        if not domain:
            logger.debug(f"[CapabilityScorer] unknown task_type={task_type}, skipping")
            return 0.5
        return self.update_score(
            domain=domain,
            success=success,
            duration_s=duration_s,
            errors=errors,
            retries=retries,
        )

    def get_score(self, domain: str) -> float:
        """
        Retourne le score actuel d'un domaine.

        Returns:
            Score 0.0–1.0 (0.5 si domaine inconnu)
        """
        try:
            ds = self._scores.get(domain)
            if ds is None:
                return 0.5
            return ds.compute_score()
        except Exception as exc:
            logger.warning(f"[CapabilityScorer] get_score error: {exc}")
            return 0.5

    def get_all_scores(self) -> Dict[str, float]:
        """Retourne dict {domain: score} pour tous les domaines."""
        try:
            return {domain: ds.compute_score() for domain, ds in self._scores.items()}
        except Exception as exc:
            logger.warning(f"[CapabilityScorer] get_all_scores error: {exc}")
            return {d: 0.5 for d in DOMAINS}

    def get_stats(self) -> dict:
        """Stats détaillées pour l'API / monitoring."""
        try:
            result = {}
            for domain, ds in self._scores.items():
                result[domain] = {
                    "score": ds.compute_score(),
                    "total_tasks": ds.total_tasks,
                    "success_rate": ds.success_rate,
                    "avg_duration_s": ds.avg_duration_s,
                    "avg_errors": ds.avg_errors,
                    "avg_retries": ds.avg_retries,
                    "last_updated": ds.last_updated,
                }
            return result
        except Exception as exc:
            logger.warning(f"[CapabilityScorer] get_stats error: {exc}")
            return {}

    def get_weakest_domain(self) -> Optional[str]:
        """Retourne le domaine avec le score le plus bas."""
        try:
            scores = self.get_all_scores()
            return min(scores, key=scores.get) if scores else None
        except Exception:
            return None

    def get_strongest_domain(self) -> Optional[str]:
        """Retourne le domaine avec le score le plus haut."""
        try:
            scores = self.get_all_scores()
            return max(scores, key=scores.get) if scores else None
        except Exception:
            return None

    # ── Persistence ───────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Sauvegarde dans workspace/capability_scores.json. Fail-silent."""
        try:
            os.makedirs(os.path.dirname(_PERSIST_PATH), exist_ok=True)
            data = {domain: asdict(ds) for domain, ds in self._scores.items()}
            tmp = _PERSIST_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _PERSIST_PATH)
        except Exception as exc:
            logger.warning(f"[CapabilityScorer] _persist error: {exc}")

    def _load_from_disk(self) -> None:
        """Charge depuis workspace/capability_scores.json. Fail-silent."""
        try:
            if not os.path.exists(_PERSIST_PATH):
                return
            with open(_PERSIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for domain, d in data.items():
                try:
                    self._scores[domain] = DomainScore(**d)
                except Exception:
                    logger.debug("swallowed_exception", exc_info=True)
                    continue
            logger.info(
                f"[CapabilityScorer] loaded {len(self._scores)} domain scores from disk"
            )
        except Exception as exc:
            logger.warning(f"[CapabilityScorer] _load_from_disk error: {exc}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_scorer: Optional[CapabilityScorer] = None


def get_capability_scorer() -> CapabilityScorer:
    global _scorer
    if _scorer is None:
        _scorer = CapabilityScorer()
    return _scorer
