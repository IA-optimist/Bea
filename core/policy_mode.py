"""
PolicyMode — contrôle global du comportement de Bea.
Désactivé par défaut (BALANCED). UNCENSORED agit sur raisonnement uniquement,
jamais sur ExecutionPolicy rules.
RAM : < 200 bytes (enum + singleton).
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PolicyMode(Enum):
    SAFE       = "SAFE"        # Limitations strictes, 1 agent max toujours
    BALANCED   = "BALANCED"    # Comportement actuel (défaut)
    UNCENSORED = "UNCENSORED"  # Exploration étendue — ExecutionPolicy inchangée


# Description courte pour l'app
POLICY_MODE_DESCRIPTIONS = {
    "SAFE":       "Stabilité maximale — 1 agent, risque minimal",
    "BALANCED":   "Mode normal — équilibre sécurité / autonomie",
    "UNCENSORED": "Exploration maximale — raisonnement étendu, sécurité d'exécution maintenue",
}

# Agents autorisés en bonus en mode UNCENSORED (s'ajoutent aux règles normales)
UNCENSORED_EXTRA_AGENTS = {"lens-reviewer", "map-planner", "shadow-advisor"}

# En mode SAFE, forcer complexity="low" override
SAFE_MAX_AGENTS = 1
SAFE_FORCE_COMPLEXITY = "low"


class PolicyModeStore:
    """Stockage en mémoire du mode courant. Thread-safe (GIL suffit pour lecture/écriture simple)."""

    def __init__(self):
        self._mode: PolicyMode = PolicyMode.BALANCED
        self._uncensored_activations: int = 0

    def get(self) -> PolicyMode:
        return self._mode

    def set(self, mode: str) -> bool:
        """Retourne True si changement réussi, False si mode invalide."""
        try:
            self._mode = PolicyMode(mode.upper())
            logger.info(f"[PolicyMode] changed to {self._mode.value}")
            if mode.upper() == "UNCENSORED":
                self._uncensored_activations += 1
                logging.getLogger("bea.policy").warning(
                    f"UNCENSORED mode activated (total activations: {self._uncensored_activations})"
                )
            return True
        except ValueError:
            logger.warning(f"[PolicyMode] invalid mode: {mode}")
            return False

    def get_uncensored_stats(self) -> dict:
        return {
            "current_mode": self._mode.value,
            "uncensored_activations": self._uncensored_activations,
            "is_uncensored": self._mode.value == "UNCENSORED",
        }

    def to_dict(self) -> dict:
        return {
            "current": self._mode.value,
            "description": POLICY_MODE_DESCRIPTIONS.get(self._mode.value, ""),
            "available": list(POLICY_MODE_DESCRIPTIONS.keys()),
        }


# Singleton
_store: Optional[PolicyModeStore] = None

def get_policy_mode_store() -> PolicyModeStore:
    global _store
    if _store is None:
        _store = PolicyModeStore()
    return _store
