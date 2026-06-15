"""
core.executor.constants
=======================
Shared constants for BeaOrchestrator: timeouts, type aliases, intent map.
"""
from __future__ import annotations
from typing import Callable, Awaitable

# Callback type: async function that streams text to the caller
CB = Callable[[str], Awaitable[None]]

# Global timeout per session mode (seconds)
SESSION_TIMEOUTS: dict[str, int] = {
    "auto":     600,   # 10 min — forge-builder Codex seul prend 180-300s ; les missions
                       # simples sont déjà court-circuitées vers CHAT par TaskRouter.
                       # 150s tuait TOUTE mission auto avec génération de code.
    "night":    1800,  # 30 min
    "improve":  900,   # 15 min
    "chat":     60,
    "business": 720,   # 12 min — analysts (~142s) + forge-builder Codex (~300s) + buffer
    "code":     600,
    "plan":     600,
    "research": 600,
}

# Mapping intent → composant — aucun LLM requis pour le routage
INTENT_MAP: dict[str, str] = {
    "improve":  "self_improve",     # pipeline auto-amélioration
    "code":     "forge-builder",    # génération code
    "research": "scout-research",   # recherche et synthèse
    "plan":     "map-planner",      # planification
    "night":    "night-worker",     # travail long multi-cycles
    "chat":     "shadow-advisor",   # conversation rapide
    "workflow": "workflow-agent",   # création et exécution de workflows
    "default":  "shadow-advisor",   # fallback local garanti
}
