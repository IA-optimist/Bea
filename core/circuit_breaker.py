"""
BEA MAX — CircuitBreaker
Protection contre les cascades de pannes pour Ollama et les APIs cloud.

Pattern standard à 3 états :
    CLOSED    → opérations normales (état par défaut)
    OPEN      → circuit ouvert : toutes les requêtes échouent immédiatement
    HALF_OPEN → une requête test pour vérifier la récupération

Comportement :
    - N échecs consécutifs → passe OPEN (Ollama mort, API quota, timeout réseau)
    - Cooldown_s secondes en OPEN → bascule HALF_OPEN
    - 1 succès en HALF_OPEN → retour CLOSED
    - 1 échec en HALF_OPEN → retour OPEN

Usage :
    cb = CircuitBreaker("ollama", failure_threshold=3, cooldown_s=60)

    async with cb.guard():
        # Si circuit OPEN → lève CircuitOpenError immédiatement
        result = await llm.ainvoke(...)

    # Ou wrapping :
    result = await cb.call(llm.ainvoke, messages)

Registre global :
    breaker = get_breaker("ollama")    # retourne le même objet
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from contextlib import asynccontextmanager
from typing import Callable, Awaitable, Any
import structlog

log = structlog.get_logger()

# ── Configuration par défaut ──────────────────────────────────
DEFAULT_FAILURE_THRESHOLD = 3      # échecs avant ouverture
DEFAULT_COOLDOWN_S        = 60.0   # secondes avant tentative de récupération
DEFAULT_SUCCESS_THRESHOLD = 1      # succès pour re-fermer depuis HALF_OPEN


class CircuitState(str, Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Levée quand le circuit est ouvert et qu'une requête est tentée."""
    def __init__(self, name: str, cooldown_remaining: float):
        self.name              = name
        self.cooldown_remaining = round(cooldown_remaining, 1)
        super().__init__(
            f"CircuitBreaker '{name}' OPEN — "
            f"récupération dans {self.cooldown_remaining}s"
        )


# ══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Circuit breaker thread-safe pour appels async.

    Paramètres :
        name              : identifiant (ex: "ollama", "anthropic", "openai")
        failure_threshold : N échecs consécutifs pour ouvrir le circuit
        cooldown_s        : secondes d'attente avant HALF_OPEN
        success_threshold : N succès pour re-fermer depuis HALF_OPEN
    """

    def __init__(
        self,
        name:               str,
        failure_threshold:  int   = DEFAULT_FAILURE_THRESHOLD,
        cooldown_s:         float = DEFAULT_COOLDOWN_S,
        success_threshold:  int   = DEFAULT_SUCCESS_THRESHOLD,
    ):
        self.name               = name
        self.failure_threshold  = failure_threshold
        self.cooldown_s         = cooldown_s
        self.success_threshold  = success_threshold

        self._state             = CircuitState.CLOSED
        self._failure_count     = 0
        self._success_count     = 0
        self._last_failure_ts   = 0.0
        self._total_calls       = 0
        self._total_failures    = 0
        self._total_open_blocks = 0
        self._lock              = asyncio.Lock()

    # ── État ────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    def _cooldown_remaining(self) -> float:
        """Secondes restantes avant fin du cooldown."""
        if self._state != CircuitState.OPEN:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_ts
        return max(0.0, self.cooldown_s - elapsed)

    def _should_attempt(self) -> bool:
        """True si une requête est autorisée (circuit fermé ou demi-ouvert)."""
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if self._cooldown_remaining() <= 0:
                self._state         = CircuitState.HALF_OPEN
                self._success_count = 0
                log.info("circuit_half_open", name=self.name)
                return True
            return False
        # HALF_OPEN → 1 requête de test autorisée
        return True

    # ── Enregistrement résultat ────────────────────────────

    def _on_success(self):
        self._total_calls += 1
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state         = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                log.info("circuit_closed", name=self.name)
        elif self._state == CircuitState.CLOSED:
            # Reset compteur d'échecs sur succès
            self._failure_count = 0

    def _on_failure(self, error: Exception):
        self._total_calls    += 1
        self._total_failures += 1
        self._failure_count  += 1
        self._last_failure_ts = time.monotonic()

        if self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            if self._failure_count >= self.failure_threshold:
                prev = self._state
                self._state         = CircuitState.OPEN
                self._success_count = 0
                log.warning(
                    "circuit_opened",
                    name=self.name,
                    failures=self._failure_count,
                    prev_state=prev.value,
                    err=str(error)[:80],
                )

    # ── Interface principale ───────────────────────────────

    @asynccontextmanager
    async def guard(self):
        """
        Context manager async.

        async with cb.guard():
            result = await risky_call()

        Lève CircuitOpenError si OPEN.
        """
        async with self._lock:
            if not self._should_attempt():
                self._total_open_blocks += 1
                remaining = self._cooldown_remaining()
                raise CircuitOpenError(self.name, remaining)

        try:
            yield
            async with self._lock:
                self._on_success()
        except CircuitOpenError:
            raise
        except Exception as e:
            async with self._lock:
                self._on_failure(e)
            raise

    async def call(
        self,
        fn:   Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ) -> Any:
        """
        Exécute fn(*args, **kwargs) sous protection du circuit.

        Exemple :
            result = await cb.call(llm.ainvoke, messages)
        """
        async with self.guard():
            return await fn(*args, **kwargs)

    def reset(self):
        """Remet le circuit en état CLOSED (pour tests ou reprise manuelle)."""
        self._state         = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        log.info("circuit_reset", name=self.name)

    def get_stats(self) -> dict:
        """Statistiques du circuit."""
        return {
            "name":              self.name,
            "state":             self._state.value,
            "failure_count":     self._failure_count,
            "total_calls":       self._total_calls,
            "total_failures":    self._total_failures,
            "total_open_blocks": self._total_open_blocks,
            "cooldown_remaining": self._cooldown_remaining(),
            "failure_threshold": self.failure_threshold,
            "cooldown_s":        self.cooldown_s,
        }


# ══════════════════════════════════════════════════════════════
# REGISTRE GLOBAL
# ══════════════════════════════════════════════════════════════

_REGISTRY: dict[str, CircuitBreaker] = {}

def get_breaker(
    name:               str,
    failure_threshold:  int   = DEFAULT_FAILURE_THRESHOLD,
    cooldown_s:         float = DEFAULT_COOLDOWN_S,
) -> CircuitBreaker:
    """
    Retourne (ou crée) le circuit breaker pour le nom donné.
    Thread-safe via dictionnaire Python (GIL).

    Exemple :
        cb = get_breaker("ollama", failure_threshold=3, cooldown_s=60)
        cb = get_breaker("anthropic", failure_threshold=2, cooldown_s=120)
    """
    if name not in _REGISTRY:
        _REGISTRY[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            cooldown_s=cooldown_s,
        )
    return _REGISTRY[name]


def get_all_stats() -> dict[str, dict]:
    """Retourne les stats de tous les circuit breakers."""
    return {name: cb.get_stats() for name, cb in _REGISTRY.items()}


def reset_all():
    """Remet tous les circuits en CLOSED (pour tests)."""
    for cb in _REGISTRY.values():
        cb.reset()
