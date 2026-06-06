"""
JARVIS MAX — MultimodalRouter
Route les inputs multimodaux vers le bon agent/processor.

État réel par modalité :
  text       → ACTIVE  — pipeline complet opérationnel
  image      → STUB    — détection OK, traitement non implémenté (V3)
  audio      → STUB    — détection OK, traitement non implémenté (V3)
  document   → STUB    — détection OK, traitement non implémenté (V3)
  screenshot → STUB    — détection OK, traitement non implémenté (V3)

Chaque modalité STUB retourne un dict clair avec status="not_implemented"
et un message explicite — pas d'erreur silencieuse.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Extensions reconnues pour la modalité document
_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".xlsx"}

# Statuts réels des modalités
_MODALITY_STATUS: dict[str, dict] = {
    "text":       {"status": "active",  "version_active": "V1"},
    "image":      {"status": "planned", "eta": "V3"},
    "audio":      {"status": "planned", "eta": "V3"},
    "document":   {"status": "planned", "eta": "V3"},
    "screenshot": {"status": "planned", "eta": "V3"},
}


class MultimodalRouter:
    """Route les inputs multimodaux vers le bon agent/processor."""

    SUPPORTED_MODALITIES = list(_MODALITY_STATUS.keys())

    # ── Détection de modalité ─────────────────────────────────────────────────

    def detect_modality(self, input_data: dict) -> str:
        """
        Détecte la modalité depuis le payload de la mission.

        Règles (ordre de priorité) :
          1. screenshot_base64  → "screenshot"
          2. audio_base64       → "audio"
          3. image_base64 ou image_url → "image"
          4. file_path avec extension doc → "document"
          5. sinon              → "text"
        """
        if not isinstance(input_data, dict):
            return "text"

        if input_data.get("screenshot_base64"):
            return "screenshot"

        if input_data.get("audio_base64"):
            return "audio"

        if input_data.get("image_base64") or input_data.get("image_url"):
            return "image"

        file_path = input_data.get("file_path", "")
        if file_path:
            from pathlib import Path
            ext = Path(str(file_path)).suffix.lower()
            if ext in _DOCUMENT_EXTENSIONS:
                return "document"

        return "text"

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, mission_id: str, input_data: dict) -> dict:
        """
        Retourne le plan de routing pour cette mission multimodale.

        Pour les modalités non-text : retourne un dict clair avec
        status="not_implemented" et les détails — jamais d'exception silencieuse.

        Loggue la modalité détectée.
        """
        t0 = time.monotonic()
        modality = self.detect_modality(input_data)

        log.info(
            "multimodal_router_detected",
            extra={"mission_id": mission_id, "modality": modality},
        )

        # Log dans MissionStateStore si disponible
        self._log_modality(mission_id, modality)

        if modality == "text":
            return self._route_text(mission_id, input_data, t0)
        else:
            return self._route_stub(mission_id, modality, t0)

    def _route_text(self, mission_id: str, input_data: dict, t0: float) -> dict:
        """Routing texte — pipeline complet actif."""
        goal = (
            input_data.get("goal")
            or input_data.get("input")
            or input_data.get("prompt", "")
        )
        return {
            "mission_id":  mission_id,
            "modality":    "text",
            "status":      "routed",
            "pipeline":    "mission_system → orchestrator → agent_crew",
            "agent_entry": "atlas-director",
            "payload":     {"goal": goal},
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    def _route_stub(self, mission_id: str, modality: str, t0: float) -> dict:
        """
        Routing STUB pour modalités non encore implémentées.
        Retourne un message explicite — pas d'exception.
        """
        eta = _MODALITY_STATUS.get(modality, {}).get("eta", "V3")
        return {
            "mission_id":  mission_id,
            "modality":    modality,
            "status":      "not_implemented",
            "message":     (
                f"Modality '{modality}' is not yet implemented. "
                f"Planned for {eta}. "
                f"Falling back to text processing if a 'goal' field is present."
            ),
            "fallback_available": bool(
                isinstance(self._extract_goal({}), str)
            ),
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }

    def _extract_goal(self, input_data: dict) -> str:
        return (
            input_data.get("goal")
            or input_data.get("input")
            or input_data.get("prompt", "")
        )

    def _log_modality(self, mission_id: str, modality: str) -> None:
        """Log la modalité détectée dans MissionStateStore (fail-open)."""
        try:
            from api.mission_store import MissionStateStore
            from api.models import MissionLogEvent, LogEventType

            event = MissionLogEvent(
                mission_id=mission_id,
                event_type=LogEventType.AGENT_DECISION,
                message=f"MultimodalRouter: detected modality '{modality}'",
                data={"modality": modality, "status": _MODALITY_STATUS.get(modality, {})},
            )
            MissionStateStore.get().append_log(event)
        except Exception:
            log.debug("swallowed_exception", exc_info=True)

    # ── Capabilities ──────────────────────────────────────────────────────────

    def get_capabilities(self) -> dict[str, Any]:
        """
        Retourne ce qui est réellement supporté vs planifié.
        Utilisé par GET /api/v2/system/capabilities.
        """
        modalities: dict[str, dict] = {}
        for name, info in _MODALITY_STATUS.items():
            entry: dict[str, Any] = {
                "status":      info["status"],
                "description": _MODALITY_DESCRIPTIONS.get(name, ""),
            }
            if "eta" in info:
                entry["eta"] = info["eta"]
            if "version_active" in info:
                entry["version_active"] = info["version_active"]
            modalities[name] = entry

        return {
            "modalities": modalities,
            "active":     [k for k, v in _MODALITY_STATUS.items() if v["status"] == "active"],
            "planned":    [k for k, v in _MODALITY_STATUS.items() if v["status"] == "planned"],
        }


# ── Descriptions humaines des modalités ──────────────────────────────────────

_MODALITY_DESCRIPTIONS: dict[str, str] = {
    "text":       "Texte libre — goal de mission, prompt, instructions",
    "image":      "Image base64 ou URL — analyse visuelle via LLM vision",
    "audio":      "Audio base64 — transcription STT puis traitement",
    "document":   "Fichier PDF/DOCX — extraction de contenu puis RAG",
    "screenshot": "Capture d'écran base64 — analyse visuelle et actions UI",
}


# ── Singleton ────────────────────────────────────────────────────────────────

_router_instance: MultimodalRouter | None = None


def get_multimodal_router() -> MultimodalRouter:
    """Retourne l'instance singleton du MultimodalRouter."""
    global _router_instance
    if _router_instance is None:
        _router_instance = MultimodalRouter()
    return _router_instance
