"""dynamic_connector — connecteurs créés à la volée depuis un *spec* (auto-extension).

Permet à Béa de **s'ajouter un connecteur au besoin** : l'agent (ou un humain)
fournit un descriptif déclaratif (nom, base_url, header d'auth, actions→endpoints)
et un connecteur HTTP opérationnel est construit + enregistré dans le registre, sans
écrire de fichier. Pensé pour être appelé par `tool_builder`/self-improvement.

Spec attendu :
    {
      "name": "weather",
      "description": "Météo via API X",
      "base_url": "https://api.x.com",
      "auth_header": {"Authorization": "Bearer ${WEATHER_TOKEN}"},   # ${ENV} résolu au runtime
      "actions": {
        "forecast": {"method": "GET", "path": "/v1/forecast/{city}"}
      }
    }
"""
from __future__ import annotations

import os
import re

from .base import ConnectorBase, ConnectorRegistry, ConnectorResult, get_connector_registry

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


class SpecError(ValueError):
    """Spec de connecteur invalide."""


def _resolve_env(value: str) -> str:
    """Remplace ${VAR} par os.environ['VAR'] (secrets hors-code)."""
    return _ENV_RE.sub(lambda m: os.getenv(m.group(1), ""), value)


def validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise SpecError("spec doit être un dict")
    name = spec.get("name", "")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SpecError(f"name invalide: {name!r} (attendu [a-z][a-z0-9_]+)")
    base = spec.get("base_url", "")
    if not isinstance(base, str) or not base.startswith("https://"):
        raise SpecError("base_url doit commencer par https://")
    actions = spec.get("actions", {})
    if not isinstance(actions, dict) or not actions:
        raise SpecError("actions doit être un dict non vide")
    for act, cfg in actions.items():
        if not isinstance(cfg, dict) or cfg.get("method", "GET").upper() not in {
            "GET", "POST", "PUT", "PATCH", "DELETE"
        }:
            raise SpecError(f"action '{act}': method invalide")
        if not isinstance(cfg.get("path", ""), str) or not cfg["path"].startswith("/"):
            raise SpecError(f"action '{act}': path doit commencer par /")


class DynamicConnector(ConnectorBase):
    """Connecteur HTTP générique piloté par un spec déclaratif."""

    def __init__(self, spec: dict) -> None:
        validate_spec(spec)
        self._spec = spec
        self.name = spec["name"]
        self.description = spec.get("description", "")
        self.actions = list(spec["actions"].keys())
        self._base_url = spec["base_url"].rstrip("/")
        self._auth_header = spec.get("auth_header", {}) or {}

    def is_configured(self) -> bool:
        # configuré si tous les ${ENV} du header d'auth sont résolus
        for v in self._auth_header.values():
            for var in _ENV_RE.findall(str(v)):
                if not os.getenv(var):
                    return False
        return True

    def execute(self, action: str, params: dict) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)
        cfg = self._spec["actions"].get(action)
        if not cfg:
            result.error = f"Unknown action: {action}"
            return result
        method = cfg.get("method", "GET").upper()
        # substitution des {placeholders} du path depuis params (échappés)
        try:
            path = cfg["path"].format(**{k: str(v) for k, v in (params or {}).items()})
        except KeyError as e:
            result.error = f"paramètre manquant pour le path: {e}"
            return result
        url = self._base_url + path
        headers = {k: _resolve_env(str(v)) for k, v in self._auth_header.items()}
        body = params.get("body") if isinstance(params, dict) else None
        try:
            from .api_connectors import _http_request
            status, text = _http_request(method, url, headers=headers, json_body=body)
            result.success = 200 <= status < 300
            result.output = {"status": status, "body": text}
            if not result.success:
                result.error = f"http_{status}: {text[:200]}"
        except Exception as e:
            result.error = str(e)[:200]
        return result


def register_connector_from_spec(spec: dict, registry: ConnectorRegistry | None = None) -> DynamicConnector:
    """Construit un DynamicConnector depuis `spec` et l'enregistre. Lève SpecError si invalide."""
    connector = DynamicConnector(spec)
    (registry or get_connector_registry()).register(connector)
    return connector
