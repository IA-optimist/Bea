"""Legacy mission endpoint helpers."""
from __future__ import annotations

from typing import Any


async def legacy_health_payload() -> Any:
    """Delegate the legacy /api/health alias to the v2 system health handler."""
    from api.routes.system import health

    return await health()


def legacy_stats_payload(get_mission_system) -> dict[str, Any]:
    """Build the legacy /api/stats payload used by mobile clients."""
    try:
        mission_system = get_mission_system()
        return {"ok": True, "data": {"missions": mission_system.stats()}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

async def legacy_stream_response(mission_id: str) -> Any:
    """Build the legacy SSE stream response for a mission."""
    from api.routes.mission_control import _sse_generator
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _sse_generator(mission_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
