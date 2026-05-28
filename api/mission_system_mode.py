"""System mode helpers for mission routes."""
from __future__ import annotations

from typing import Any


def get_system_mode_payload() -> dict[str, Any]:
    """Return the current system mode API payload."""
    try:
        from core.mode_system import get_mode_system

        mode_system = get_mode_system()
        return {"ok": True, "data": mode_system.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def set_system_mode_payload(mode: str, changed_by: str) -> dict[str, Any]:
    """Set the system mode and return the updated API payload."""
    try:
        from core.mode_system import get_mode_system

        mode_system = get_mode_system()
        mode_system.set_mode(mode.upper(), changed_by=changed_by)
        return {"ok": True, "data": mode_system.to_dict()}
    except ValueError:
        raise
    except Exception as exc:
        return {"ok": False, "error": str(exc)}