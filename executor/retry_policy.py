"""
BEA MAX — Retry Policy v2
Politique de retry avec exponential backoff et jitter.

Utilise uniquement la stdlib Python (pas de tenacity).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# ── Types d'erreurs ────────────────────────────────────────────────────────────

# Erreurs retryables : problèmes transitoires réseau / IO
_RETRYABLE_TYPES = (TimeoutError, ConnectionError, OSError)

# Erreurs NON retryables : bugs logiques, erreurs de programmation
_NON_RETRYABLE_TYPES = (
    ValueError,
    TypeError,
    AssertionError,
    KeyboardInterrupt,
    SystemExit,
    NotImplementedError,
    AttributeError,
    ImportError,
)

# Mots-clés dans le message qui signalent une erreur transitoire
_RETRYABLE_SUBSTRINGS = (
    "timeout", "connect", "network", "temporary", "unavailable",
    "overloaded", "rate limit", "503", "502", "429", "reset by peer",
)


# ── Fonctions publiques ────────────────────────────────────────────────────────

def is_retryable(error: BaseException) -> bool:
    """
    Détermine si une exception justifie un retry.

    Règles :
    - Les erreurs non-retryables (ValueError, TypeError…) → False TOUJOURS
    - Les erreurs réseau/IO connues → True
    - Les autres : on inspecte le message pour des mots-clés transitoires
    """
    if isinstance(error, _NON_RETRYABLE_TYPES):
        return False
    if isinstance(error, _RETRYABLE_TYPES):
        return True
    msg = str(error).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)


def should_retry(attempt: int, error: BaseException, policy: "RetryPolicy") -> bool:
    """
    Retourne True si la tâche doit être retentée.

    Conditions :
    1. L'erreur est retryable
    2. Le nombre de tentatives n'a pas dépassé max_attempts
    """
    if not is_retryable(error):
        return False
    return attempt < policy.max_attempts


def compute_delay(attempt: int, policy: "RetryPolicy") -> float:
    """
    Calcule le délai avant la prochaine tentative (exponential backoff + jitter).

    attempt : numéro de la tentative courante (1-indexed)
    Retourne un délai en secondes, clampé entre 0 et policy.max_delay.
    """
    # Backoff exponentiel : base * factor^(attempt-1)
    raw = policy.base_delay * (policy.backoff_factor ** (attempt - 1))
    capped = min(raw, policy.max_delay)

    # Jitter : ±30% du délai pour éviter le thundering herd
    jitter = capped * 0.3 * (random.random() * 2 - 1)
    final = max(0.05, capped + jitter)

    return round(final, 3)


# ── RetryPolicy ───────────────────────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """
    Politique de retry configurable pour une tâche.

    Valeurs par défaut conservatrices (3 essais, backoff x2, max 30s).
    """
    max_attempts:    int   = 3
    base_delay:      float = 1.0       # secondes
    max_delay:       float = 30.0      # secondes
    backoff_factor:  float = 2.0
    retryable_errors: tuple[type[BaseException], ...] = field(default_factory=lambda: _RETRYABLE_TYPES)

    def should_retry(self, attempt: int, error: BaseException) -> bool:
        return should_retry(attempt, error, self)

    def compute_delay(self, attempt: int) -> float:
        return compute_delay(attempt, self)


# ── Presets ───────────────────────────────────────────────────────────────────

DEFAULT_POLICY = RetryPolicy()
FAST_POLICY    = RetryPolicy(max_attempts=2, base_delay=0.5, max_delay=5.0)
AGGRESSIVE_POLICY = RetryPolicy(max_attempts=5, base_delay=2.0, max_delay=60.0)
