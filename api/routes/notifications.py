"""
api/routes/notifications.py — Notification subscription endpoints
Allows users to subscribe/unsubscribe to mission notifications
"""
from __future__ import annotations
from typing import Annotated, Optional
import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator

from api._deps import _check_auth
from core.notifications import (
    get_notification_service,
    NotificationChannel,
)
from core.notifications.telegram_client import TelegramNotificationClient

log = structlog.get_logger()
router = APIRouter(tags=["notifications"])


# ── Pydantic models ───────────────────────────────────────────

class SubscribeRequest(BaseModel):
    """Notification subscription request"""
    channel: str  # "email" or "telegram"
    destination: str  # email address or telegram chat_id
    mission_statuses: Optional[list[str]] = None  # ["DONE", "FAILED"] by default
    
    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        v = v.lower()
        if v not in ("email", "telegram"):
            raise ValueError("channel must be 'email' or 'telegram'")
        return v
    
    @field_validator("destination")
    @classmethod
    def validate_destination(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("destination cannot be empty")
        return v


class UnsubscribeRequest(BaseModel):
    """Notification unsubscribe request"""
    channel: str  # "email" or "telegram"
    
    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        v = v.lower()
        if v not in ("email", "telegram"):
            raise ValueError("channel must be 'email' or 'telegram'")
        return v


class TestNotificationRequest(BaseModel):
    """Test notification request"""
    channel: str
    destination: str
    
    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        v = v.lower()
        if v not in ("email", "telegram"):
            raise ValueError("channel must be 'email' or 'telegram'")
        return v


# ── API Routes ────────────────────────────────────────────────

@router.post("/api/v2/notifications/subscribe")
async def subscribe_notifications(
    req: SubscribeRequest,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Subscribe to mission notifications
    
    Allows users to receive push notifications when missions complete (DONE)
    or fail (FAILED) via email or Telegram.
    
    **Example (Telegram):**
    ```json
    {
        "channel": "telegram",
        "destination": "123456789",
        "mission_statuses": ["DONE", "FAILED"]
    }
    ```
    
    **Example (Email):**
    ```json
    {
        "channel": "email",
        "destination": "user@example.com",
        "mission_statuses": ["DONE", "FAILED"]
    }
    ```
    
    **Telegram Setup:**
    1. Message @BotFather to create a bot and get token
    2. Set TELEGRAM_BOT_TOKEN in .env
    3. Start chat with your bot
    4. Get your chat_id (use /start or inspect update webhook)
    5. Subscribe with your chat_id as destination
    
    **Email Setup:**
    Configure SMTP settings in .env:
    - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
    """
    _check_auth(x_jarvis_token, authorization)
    
    # Extract user_id from token (simplified - use "default" for now)
    # In production, parse JWT token to get actual user_id
    user_id = "default"
    
    service = get_notification_service()
    
    try:
        channel = NotificationChannel(req.channel)
        subscription = service.subscribe(
            user_id=user_id,
            channel=channel,
            destination=req.destination,
            mission_statuses=req.mission_statuses or ["DONE", "FAILED"],
        )
        
        log.info("notification_subscription_created_via_api",
                 user_id=user_id,
                 channel=req.channel,
                 destination=req.destination)
        
        return {
            "ok": True,
            "data": {
                "message": f"Subscribed to {req.channel} notifications",
                "channel": req.channel,
                "destination": req.destination,
                "mission_statuses": subscription.mission_statuses,
            }
        }
    
    except Exception as e:
        log.error("notification_subscription_failed",
                  error=str(e),
                  channel=req.channel)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v2/notifications/unsubscribe")
async def unsubscribe_notifications(
    req: UnsubscribeRequest,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Unsubscribe from mission notifications
    
    Removes notification subscription for specified channel.
    
    **Example:**
    ```json
    {
        "channel": "telegram"
    }
    ```
    """
    _check_auth(x_jarvis_token, authorization)
    user_id = "default"
    
    service = get_notification_service()
    
    try:
        channel = NotificationChannel(req.channel)
        success = service.unsubscribe(user_id=user_id, channel=channel)
        
        if success:
            log.info("notification_subscription_removed_via_api",
                     user_id=user_id,
                     channel=req.channel)
            return {
                "ok": True,
                "data": {
                    "message": f"Unsubscribed from {req.channel} notifications",
                    "channel": req.channel,
                }
            }
        else:
            return {
                "ok": False,
                "error": f"No active subscription found for {req.channel}",
            }
    
    except Exception as e:
        log.error("notification_unsubscribe_failed",
                  error=str(e),
                  channel=req.channel)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/notifications/subscriptions")
async def get_subscriptions(
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Get all active notification subscriptions for current user
    
    Returns list of active subscriptions with channels and destinations.
    """
    _check_auth(x_jarvis_token, authorization)
    user_id = "default"
    
    service = get_notification_service()
    subscriptions = service.get_subscriptions(user_id)
    
    return {
        "ok": True,
        "data": {
            "subscriptions": [
                {
                    "channel": sub.channel.value,
                    "destination": sub.destination,
                    "enabled": sub.enabled,
                    "mission_statuses": sub.mission_statuses,
                    "created_at": sub.created_at,
                }
                for sub in subscriptions
            ]
        }
    }


@router.post("/api/v2/notifications/test")
async def test_notification(
    req: TestNotificationRequest,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """
    Send a test notification
    
    Sends a test message to verify notification configuration.
    Useful for testing Telegram bot setup or email delivery.
    
    **Example:**
    ```json
    {
        "channel": "telegram",
        "destination": "123456789"
    }
    ```
    """
    _check_auth(x_jarvis_token, authorization)
    
    try:
        from core.notifications.models import NotificationPayload
        
        test_payload = NotificationPayload(
            mission_id="test-notification",
            user_id="test",
            status="DONE",
            title="Test Notification from JarvisMax",
            result="If you receive this message, your notification setup is working correctly!",
        )
        
        if req.channel == "telegram":
            client = TelegramNotificationClient()
            success = await client.send(req.destination, test_payload)
        elif req.channel == "email":
            from core.notifications.email_client import EmailNotificationClient
            client = EmailNotificationClient()
            success = await client.send(req.destination, test_payload)
        else:
            raise HTTPException(status_code=400, detail="Invalid channel")
        
        if success:
            return {
                "ok": True,
                "data": {
                    "message": "Test notification sent successfully",
                    "channel": req.channel,
                    "destination": req.destination,
                }
            }
        else:
            return {
                "ok": False,
                "error": "Failed to send test notification. Check logs for details.",
            }
    
    except Exception as e:
        log.error("test_notification_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
