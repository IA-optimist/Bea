"""user_model — modèle persistant de l'utilisateur (Axe 2, inspiration Honcho/Hermes).

Stocke des *traits* stables (préférences, faits) clé→valeur avec source et
horodatage, dans un fichier JSON profil-isolé. Additif : aucun système existant
n'est modifié ; destiné à être injecté en lecture seule dans le prompt (tier
« context ») une fois validé.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class UserModel:
    """Traits utilisateur persistés en JSON (atomique, tolérant aux pannes)."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._traits: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._traits = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            # fichier corrompu/illisible → on repart d'un modèle vide (fail-open)
            self._traits = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._traits, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # remplacement atomique

    def set_trait(self, key: str, value: Any, source: str = "observed") -> None:
        if not isinstance(key, str) or not key.strip():
            return
        self._traits[key] = {"value": value, "source": source, "ts": time.time()}
        self._save()

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._traits.get(key)
        return entry["value"] if entry else default

    def forget(self, key: str) -> bool:
        if key in self._traits:
            del self._traits[key]
            self._save()
            return True
        return False

    def as_dict(self) -> dict[str, Any]:
        return {k: v["value"] for k, v in self._traits.items()}

    def summary(self, limit: int = 20) -> str:
        """Bloc texte compact pour injection au prompt (tier context)."""
        items = sorted(self._traits.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
        lines = [f"- {k}: {v['value']}" for k, v in items[:limit]]
        return "Profil utilisateur connu:\n" + "\n".join(lines) if lines else ""
