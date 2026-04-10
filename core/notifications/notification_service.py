"""
Core notification service
Manages subscriptions and dispatches notifications to appropriate channels
"""
from __future__ import annotations
import asyncio
import json
import structlog
from pathlib import Path
from typing import Optional
from .models import (
    NotificationChannel,
    NotificationPayload,
    NotificationPriority,
    NotificationSubscription,
)

log = structlog.get_logger()

# Storage file for subscriptions (simple JSON, can be migrated to DB later)
_STORAGE_PATH = Path("workspace/notifications_subscriptions.json")

# Singleton instance
_service_instance: Optional[NotificationService] = None


class NotificationService:
    """
    Central notification service
    - Manages user subscriptions
    - Dispatches notifications to channels (Telegram, Email)
    - Stores subscription data
    """
    
    def __init__(self):
        self.subscriptions: dict[str, list[NotificationSubscription]] = {}
        self._load_subscriptions()
        self._clients = {}  # Lazy-loaded channel clients
        
    def _load_subscriptions(self):
        """Load subscriptions from disk"""
        try:
            if _STORAGE_PATH.exists():
                with open(_STORAGE_PATH, "r") as f:
                    data = json.load(f)
                    for user_id, subs in data.items():
                        self.subscriptions[user_id] = [
                            NotificationSubscription(
                                user_id=s["user_id"],
                                channel=NotificationChannel(s["channel"]),
                                destination=s["destination"],
                                enabled=s.get("enabled", True),
                                mission_statuses=s.get("mission_statuses", ["DONE", "FAILED"]),
                                priority_filter=NotificationPriority(s["priority_filter"]) if s.get("priority_filter") else None,
                                created_at=s.get("created_at", 0),
                            )
                            for s in subs
                        ]
                log.info("notification_subscriptions_loaded", count=len(self.subscriptions))
        except Exception as e:
            log.warning("notification_subscriptions_load_failed", error=str(e))
            self.subscriptions = {}
    
    def _save_subscriptions(self):
        """Persist subscriptions to disk"""
        try:
            _STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                user_id: [s.to_dict() for s in subs]
                for user_id, subs in self.subscriptions.items()
            }
            with open(_STORAGE_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log.error("notification_subscriptions_save_failed", error=str(e))
    
    def subscribe(
        self,
        user_id: str,
        channel: NotificationChannel,
        destination: str,
        mission_statuses: Optional[list[str]] = None,
    ) -> NotificationSubscription:
        """
        Subscribe user to notifications
        
        Args:
            user_id: User identifier
            channel: Notification channel (email/telegram)
            destination: Email address or Telegram chat_id
            mission_statuses: List of statuses to notify (default: DONE, FAILED)
        
        Returns:
            NotificationSubscription object
        """
        if mission_statuses is None:
            mission_statuses = ["DONE", "FAILED"]
        
        sub = NotificationSubscription(
            user_id=user_id,
            channel=channel,
            destination=destination,
            mission_statuses=mission_statuses,
        )
        
        if user_id not in self.subscriptions:
            self.subscriptions[user_id] = []
        
        # Remove existing subscription with same channel
        self.subscriptions[user_id] = [
            s for s in self.subscriptions[user_id]
            if s.channel != channel
        ]
        
        self.subscriptions[user_id].append(sub)
        self._save_subscriptions()
        
        log.info("notification_subscription_created",
                 user_id=user_id,
                 channel=channel.value,
                 destination=destination)
        
        return sub
    
    def unsubscribe(self, user_id: str, channel: NotificationChannel) -> bool:
        """Remove subscription for a channel"""
        if user_id in self.subscriptions:
            original_count = len(self.subscriptions[user_id])
            self.subscriptions[user_id] = [
                s for s in self.subscriptions[user_id]
                if s.channel != channel
            ]
            if len(self.subscriptions[user_id]) < original_count:
                self._save_subscriptions()
                log.info("notification_subscription_removed",
                         user_id=user_id,
                         channel=channel.value)
                return True
        return False
    
    def get_subscriptions(self, user_id: str) -> list[NotificationSubscription]:
        """Get all subscriptions for a user"""
        return self.subscriptions.get(user_id, [])
    
    async def send_notification(self, payload: NotificationPayload):
        """
        Send notification to all subscribed channels for user
        
        Args:
            payload: NotificationPayload with mission info
        """
        user_id = payload.user_id
        subs = self.get_subscriptions(user_id)
        
        if not subs:
            log.debug("no_notification_subscriptions", user_id=user_id)
            return
        
        # Filter subscriptions by mission status
        active_subs = [
            s for s in subs
            if s.enabled and payload.status in s.mission_statuses
        ]
        
        if not active_subs:
            log.debug("no_active_subscriptions_for_status",
                      user_id=user_id,
                      status=payload.status)
            return
        
        # Send to each channel
        tasks = []
        for sub in active_subs:
            task = self._send_to_channel(sub, payload)
            tasks.append(task)
        
        # Execute all sends concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        log.info("notification_dispatch_complete",
                 user_id=user_id,
                 mission_id=payload.mission_id,
                 total=len(tasks),
                 success=success_count)
    
    async def _send_to_channel(
        self,
        subscription: NotificationSubscription,
        payload: NotificationPayload,
    ) -> bool:
        """Send notification via specific channel"""
        try:
            client = self._get_client(subscription.channel)
            if client is None:
                log.warning("notification_channel_not_configured",
                            channel=subscription.channel.value)
                return False
            
            success = await client.send(
                destination=subscription.destination,
                payload=payload,
            )
            
            if success:
                log.info("notification_sent",
                         channel=subscription.channel.value,
                         mission_id=payload.mission_id,
                         user_id=payload.user_id)
            else:
                log.warning("notification_send_failed",
                            channel=subscription.channel.value,
                            mission_id=payload.mission_id)
            
            return success
        except Exception as e:
            log.error("notification_send_error",
                      channel=subscription.channel.value,
                      error=str(e),
                      mission_id=payload.mission_id)
            return False
    
    def _get_client(self, channel: NotificationChannel):
        """Lazy-load channel client"""
        if channel not in self._clients:
            if channel == NotificationChannel.TELEGRAM:
                from .telegram_client import TelegramNotificationClient
                self._clients[channel] = TelegramNotificationClient()
            elif channel == NotificationChannel.EMAIL:
                from .email_client import EmailNotificationClient
                self._clients[channel] = EmailNotificationClient()
        
        return self._clients.get(channel)


def get_notification_service() -> NotificationService:
    """Get singleton notification service instance"""
    global _service_instance
    if _service_instance is None:
        _service_instance = NotificationService()
    return _service_instance


async def send_notification(user_id: str, mission_id: str, status: str, title: str, result: str = "", error: str = ""):
    """
    Convenience function to send notification
    
    Args:
        user_id: User identifier
        mission_id: Mission ID
        status: Mission status (DONE, FAILED, etc.)
        title: Mission title/goal
        result: Mission result (for DONE status)
        error: Error message (for FAILED status)
    """
    service = get_notification_service()
    payload = NotificationPayload(
        mission_id=mission_id,
        user_id=user_id,
        status=status,
        title=title,
        result=result,
        error=error,
    )
    await service.send_notification(payload)
