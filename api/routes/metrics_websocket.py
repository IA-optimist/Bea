"""
WebSocket endpoint for real-time metrics streaming.
Endpoint: /ws/metrics
Streams: CPU, memory, missions count, revenue data every 2 seconds.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse

from api._deps import require_auth

log = structlog.get_logger()

router = APIRouter(tags=["metrics", "websocket"])

# Track active WebSocket connections
active_connections: set[WebSocket] = set()


def get_system_metrics() -> dict:
    """Collect real-time system metrics."""
    try:
        import psutil

        cpu_usage = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        memory_used_gb = memory.used / (1024 ** 3)
        memory_total_gb = memory.total / (1024 ** 3)
    except ImportError:
        log.warning("psutil_not_available", hint="pip install psutil for system monitoring")
        cpu_usage = 0
        memory_usage = 0
        memory_used_gb = 0
        memory_total_gb = 0

    return {
        "cpu": round(cpu_usage, 2),
        "memory": round(memory_usage, 2),
        "memory_used_gb": round(memory_used_gb, 2),
        "memory_total_gb": round(memory_total_gb, 2),
    }


def get_missions_metrics() -> dict:
    """Get missions statistics from MissionSystem (live data)."""
    try:
        from core.mission_system import get_mission_system
        ms = get_mission_system()
        all_missions = ms.list_missions(limit=10000)
        total = len(all_missions)
        done = sum(1 for m in all_missions if getattr(m.status, 'value', str(m.status)) in ('DONE', 'COMPLETED'))
        approved = sum(1 for m in all_missions if getattr(m.status, 'value', str(m.status)) == 'APPROVED')
        pending = sum(1 for m in all_missions if getattr(m.status, 'value', str(m.status)) in ('PENDING', 'AWAITING_APPROVAL', 'READY'))
        return {"total": total, "approved": approved, "done": done, "pending": pending}
    except Exception as e:
        log.warning("missions_metrics_error", err=str(e)[:80])
        return {"total": 0, "approved": 0, "done": 0, "pending": 0}


def get_revenue_metrics() -> dict:
    """Get revenue metrics from PostgreSQL revenue_streams table."""
    try:
        from sqlalchemy import text, create_engine
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            raise ValueError("DATABASE_URL not set")
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COALESCE(SUM(monthly_amount), 0) as mrr FROM revenue_streams WHERE status='active'"
            )).fetchone()
            mrr = float(result[0]) if result else 0.0
        return {
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
            "daily_revenue": round(mrr / 30, 2),
        }
    except Exception as e:
        log.warning("revenue_metrics_error", err=str(e)[:80])
        return {
            "mrr": 0,
            "arr": 0,
            "daily_revenue": 0,
        }


def get_realtime_metrics() -> dict:
    """Aggregate all real-time metrics."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": get_system_metrics(),
        "missions": get_missions_metrics(),
        "revenue": get_revenue_metrics(),
    }


@router.websocket("/ws/metrics")
async def metrics_websocket(
    websocket: WebSocket,
    interval: int = Query(default=2, ge=1, le=10, description="Update interval in seconds")
):
    """
    WebSocket endpoint for real-time metrics streaming.
    
    Args:
        websocket: WebSocket connection
        interval: Update interval in seconds (default: 2, min: 1, max: 10)
    
    Streams JSON messages with format:
    {
        "timestamp": "2024-01-01T12:00:00",
        "system": {"cpu": 45.2, "memory": 62.5, ...},
        "missions": {"total": 450, "approved": 320, ...},
        "revenue": {"mrr": 12500, "arr": 150000, ...}
    }
    """
    await websocket.accept()
    active_connections.add(websocket)

    log.info(
        "websocket_connected",
        client=websocket.client.host if websocket.client else "unknown",
        interval=interval,
        active_connections=len(active_connections)
    )

    try:
        while True:
            # Collect metrics
            metrics = get_realtime_metrics()

            # Send to client
            await websocket.send_json(metrics)

            # Wait for next interval
            await asyncio.sleep(interval)

    except WebSocketDisconnect:
        log.info(
            "websocket_disconnected",
            client=websocket.client.host if websocket.client else "unknown",
            active_connections=len(active_connections) - 1
        )
    except Exception as e:
        log.error(
            "websocket_error",
            err=str(e),
            error_type=type(e).__name__
        )
    finally:
        active_connections.discard(websocket)


@router.get("/metrics/websocket/status")
async def websocket_status(_user: dict = Depends(require_auth)):
    """Get WebSocket metrics status."""
    return JSONResponse({
        "active_connections": len(active_connections),
        "endpoint": "/ws/metrics",
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/metrics/snapshot")
async def metrics_snapshot(_user: dict = Depends(require_auth)):
    """
    Get a one-time snapshot of current metrics.
    Useful for testing or initial page load before WebSocket connection.
    Auth required — leaks system/revenue data.
    """
    return JSONResponse(get_realtime_metrics())
