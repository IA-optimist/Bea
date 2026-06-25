from enum import Enum


class PermissionLevel(str, Enum):
    AUTO = "auto"                  # Exécution automatique, pas d'approbation
    REQUIRES_APPROVAL = "approval" # Bloque et notifie pour approbation humaine
    BLOCKED = "blocked"            # Toujours refusé
