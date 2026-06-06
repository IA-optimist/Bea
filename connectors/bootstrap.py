"""bootstrap — enregistrement des connecteurs intégrés (opt-in, sans effet de bord).

À appeler explicitement au démarrage (ex. dans `api/main.py`) :
    from connectors.bootstrap import register_builtin_connectors
    register_builtin_connectors()

Ne fait rien à l'import (pas d'effet de bord). Chaque connecteur reste inerte tant
qu'il n'est pas configuré (credentials) et peut être désactivé par
CONNECTOR_<NAME>_ENABLED=0.
"""
from __future__ import annotations

from .base import ConnectorRegistry, get_connector_registry


def register_builtin_connectors(registry: ConnectorRegistry | None = None) -> list[str]:
    """Instancie + enregistre tous les connecteurs intégrés. Renvoie les noms enregistrés."""
    reg = registry or get_connector_registry()
    registered: list[str] = []

    # Import paresseux pour éviter tout coût/effet de bord à l'import du module.
    candidates = []
    try:
        from .api_connectors import (
            DiscordConnector,
            NotionConnector,
            SlackConnector,
            TelegramConnector,
        )
        candidates += [SlackConnector, TelegramConnector, DiscordConnector, NotionConnector]
    except Exception:
        pass
    try:
        from .email_connector import EmailConnector
        candidates.append(EmailConnector)
    except Exception:
        pass

    for cls in candidates:
        try:
            inst = cls()
            reg.register(inst)
            registered.append(inst.name)
        except Exception:
            continue
    return registered
