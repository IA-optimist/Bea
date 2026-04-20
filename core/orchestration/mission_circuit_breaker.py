"""Mission circuit breaker — two-state CLOSED/OPEN switch.

Extrait depuis core/meta_orchestrator.py pour isoler la logique thread-safe
du cut-off en cas de pannes consécutives. Utilisé par MetaOrchestrator pour
court-circuiter l'exécution quand trop de délégués échouent d'affilée.
"""
from __future__ import annotations

import threading
import time

import structlog

log = structlog.get_logger(__name__)


class MissionCircuitBreaker:
    """Simple two-state circuit breaker (CLOSED / OPEN).

    CLOSED → opération normale.
    OPEN   → fast-fail pendant ``reset_s`` secondes après ``failure_threshold``
             échecs consécutifs, puis auto-reset en CLOSED pour la prochaine
             sonde.

    Thread-safe. Ne lève jamais.
    """

    def __init__(self, failure_threshold: int = 5, reset_s: float = 60.0):
        self._threshold = failure_threshold
        self._reset_s = reset_s
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        """True si le breaker est ouvert (fast-fail)."""
        with self._lock:
            if self._open_until == 0.0:
                return False
            if time.time() >= self._open_until:
                # Auto-reset : laisse passer une sonde.
                self._open_until = 0.0
                self._failures = 0
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._open_until = time.time() + self._reset_s
                log.warning(
                    "meta_orchestrator.circuit_open",
                    failures=self._failures,
                    open_for_s=self._reset_s,
                )

    def status(self) -> dict:
        with self._lock:
            return {
                "open": self._open_until > time.time(),
                "failures": self._failures,
                "open_until": self._open_until,
            }


__all__ = ["MissionCircuitBreaker"]
