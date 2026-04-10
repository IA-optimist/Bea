"""
Mission event hooks for notifications
Integrates notification system with mission lifecycle events
"""
from __future__ import annotations
import asyncio
import structlog
from typing import Optional
from .notification_service import send_notification

log = structlog.get_logger()


async def on_mission_status_change(
    mission_id: str,
    user_id: str,
    old_status: str,
    new_status: str,
    goal: str = "",
    result: str = "",
    error: str = "",
):
    """
    Hook called when mission status changes
    Triggers notifications for terminal statuses (DONE, FAILED)
    
    Args:
        mission_id: Mission identifier
        user_id: User who owns the mission
        old_status: Previous mission status
        new_status: New mission status
        goal: Mission goal/title
        result: Mission result (for DONE status)
        error: Error message (for FAILED status)
    """
    # Only notify on terminal statuses
    terminal_statuses = ["DONE", "COMPLETED", "FAILED", "CANCELLED"]
    
    if new_status not in terminal_statuses:
        return
    
    # Skip if already was in terminal status (avoid duplicate notifications)
    if old_status in terminal_statuses:
        return
    
    try:
        # Send notification asynchronously
        await send_notification(
            user_id=user_id,
            mission_id=mission_id,
            status=new_status,
            title=goal or f"Mission {mission_id}",
            result=result if new_status in ("DONE", "COMPLETED") else "",
            error=error if new_status == "FAILED" else "",
        )
        
        log.info("mission_notification_triggered",
                 mission_id=mission_id,
                 status=new_status,
                 user_id=user_id)
    
    except Exception as e:
        # Never let notification errors break mission execution
        log.error("mission_notification_error",
                  error=str(e),
                  mission_id=mission_id,
                  status=new_status)


def trigger_mission_notification_sync(
    mission_id: str,
    user_id: str,
    status: str,
    goal: str = "",
    result: str = "",
    error: str = "",
):
    """
    Synchronous wrapper for triggering mission notifications
    Creates event loop if needed and runs notification in background
    
    Use this from synchronous code paths.
    """
    try:
        # Try to get current event loop
        try:
            loop = asyncio.get_running_loop()
            # If we're in an async context, schedule as task
            asyncio.create_task(
                on_mission_status_change(
                    mission_id=mission_id,
                    user_id=user_id,
                    old_status="",  # Unknown in sync context
                    new_status=status,
                    goal=goal,
                    result=result,
                    error=error,
                )
            )
        except RuntimeError:
            # No event loop running, create new one
            asyncio.run(
                on_mission_status_change(
                    mission_id=mission_id,
                    user_id=user_id,
                    old_status="",
                    new_status=status,
                    goal=goal,
                    result=result,
                    error=error,
                )
            )
    except Exception as e:
        log.error("sync_notification_trigger_failed",
                  error=str(e),
                  mission_id=mission_id)
