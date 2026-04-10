"""
JarvisMax Notification System
Push notifications for mission status changes (DONE/FAILED)
"""
from .notification_service import (
    get_notification_service,
    send_notification,
    NotificationChannel,
    NotificationPriority,
)
from .telegram_client import TelegramNotificationClient
from .email_client import EmailNotificationClient

__all__ = [
    "get_notification_service",
    "send_notification",
    "NotificationChannel",
    "NotificationPriority",
    "TelegramNotificationClient",
    "EmailNotificationClient",
]
