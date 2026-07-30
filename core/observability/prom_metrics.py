"""
Métriques Prometheus pour Béa.
Importer ce module au démarrage de l'API pour enregistrer toutes les métriques.

Usage:
    from core.observability.prom_metrics import METRICS
    METRICS.missions_completed.inc()
    METRICS.mission_duration.observe(elapsed)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


class _NoOp:
    """Silent stub when prometheus_client is not installed."""
    def inc(self, *a, **kw): pass
    def dec(self, *a, **kw): pass
    def set(self, *a, **kw): pass
    def observe(self, *a, **kw): pass
    def labels(self, **kw): return self


def _make(factory, *args, **kwargs):
    if not _PROMETHEUS_AVAILABLE:
        return _NoOp()
    try:
        return factory(*args, **kwargs)
    except Exception as e:
        logger.warning("Métrique non enregistrée: %s", e)
        return _NoOp()


class _BEAMetrics:
    def __init__(self):
        # Missions
        self.missions_active = _make(
            Gauge, "bea_missions_active_total", "Missions actives"
        )
        self.missions_completed = _make(
            Counter, "bea_missions_completed_total", "Missions terminées avec succès"
        )
        self.missions_failed = _make(
            Counter, "bea_missions_failed_total", "Missions échouées"
        )
        self.missions_total = _make(
            Counter, "bea_missions_total", "Total missions lancées",
            labelnames=["task_type"]
        )
        self.mission_duration = _make(
            Histogram, "bea_mission_duration_seconds",
            "Durée des missions en secondes",
            buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800]
        )
        self.mission_phase = _make(
            Gauge, "bea_mission_phase_current",
            "Phase courante de mission",
            labelnames=["phase"]
        )
        self.mission_confidence = _make(
            Histogram, "bea_mission_confidence",
            "Score de confiance ConfidencePolicy",
            buckets=[0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0]
        )

        # ConfidencePolicy
        self.confidence_decisions = _make(
            Counter, "bea_confidence_policy_decisions_total",
            "Décisions par tier",
            labelnames=["tier"]
        )

        # LLM
        self.llm_calls = _make(
            Counter, "bea_llm_calls_total", "Appels LLM",
            labelnames=["provider", "role"]
        )
        self.llm_errors = _make(
            Counter, "bea_llm_errors_total", "Erreurs LLM",
            labelnames=["provider", "error_type"]
        )
        self.llm_tokens = _make(
            Counter, "bea_llm_tokens_total", "Tokens consommés",
            labelnames=["provider", "role"]
        )
        self.llm_input_tokens = _make(
            Counter, "bea_llm_input_tokens_total", "Tokens input",
            labelnames=["provider"]
        )
        self.llm_output_tokens = _make(
            Counter, "bea_llm_output_tokens_total", "Tokens output",
            labelnames=["provider"]
        )
        self.llm_fallbacks = _make(
            Counter, "bea_llm_fallbacks_total", "Fallbacks provider"
        )
        self.ollama_circuit_breaker = _make(
            Gauge, "bea_ollama_circuit_breaker_state",
            "État circuit breaker Ollama (0=CLOSED, 1=HALF, 2=OPEN)"
        )

        # Mémoire
        self.memory_queries = _make(
            Counter, "bea_memory_queries_total", "Requêtes mémoire Qdrant"
        )
        self.memory_hits = _make(
            Counter, "bea_memory_hits_total", "Résultats mémoire trouvés"
        )
        self.lessons_stored = _make(
            Counter, "bea_lessons_stored_total", "Leçons stockées"
        )

        # Context Compactor
        self.context_compactions = _make(
            Counter, "bea_context_compactions_total", "Compactions de contexte"
        )

        # Approvals
        self.approval_queue_pending = _make(
            Gauge, "bea_approval_queue_pending_total", "Approbations en attente"
        )

        # Self-improvement
        self.improvement_proposals = _make(
            Counter, "bea_improvement_proposals_total", "Proposals générées"
        )

        # Worktrees
        self.worktrees_active = _make(
            Gauge, "bea_worktrees_active_total", "Git worktrees actifs"
        )

        # Circuit breaker orchestrateur
        self.circuit_breaker_state = _make(
            Gauge, "bea_circuit_breaker_state",
            "État circuit breaker orchestrateur (0=CLOSED, 1=OPEN)"
        )


METRICS = _BEAMetrics()
