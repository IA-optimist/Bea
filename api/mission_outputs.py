"""Mission output extraction helpers for mission routes."""
from __future__ import annotations
def extract_agent_outputs(mission_id: str) -> dict:
    """Extrait le texte brut de chaque agent depuis MissionStateStore.

    Retourne {agent_name: full_output_str} — directement utilisable côté Flutter
    (Map<String, String>). Chaque agent n'apparaît qu'une fois (dernière entrée gagne).
    """
    try:
        from api.mission_store import MissionStateStore
        from api.models import LogEventType
        store  = MissionStateStore.get()
        events = store.get_log(mission_id)
        outputs: dict[str, str] = {}
        for ev in events:
            if ev.event_type != LogEventType.TOOL_RESULT:
                continue
            agent = ev.agent_id
            if not agent:
                continue
            data = ev.data or {}
            # Priorité : full_output > reasoning (structured fallback) > message brut
            text = (
                data.get("full_output")
                or (data.get("agent_result") or {}).get("reasoning")
                or ev.message
                or ""
            )
            if text:
                outputs[agent] = str(text)[:3000]
        return outputs
    except Exception:
        return {}
