"""
Notification data models
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class NotificationChannel(str, Enum):
    """Notification delivery channels"""
    EMAIL = "email"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"


class NotificationPriority(str, Enum):
    """Notification priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(str, Enum):
    """Notification delivery status"""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"


@dataclass
class NotificationSubscription:
    """User notification subscription"""
    user_id: str
    channel: NotificationChannel
    destination: str  # email address or telegram chat_id
    enabled: bool = True
    mission_statuses: list[str] = field(default_factory=lambda: ["DONE", "FAILED"])
    priority_filter: Optional[NotificationPriority] = None
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "channel": self.channel.value,
            "destination": self.destination,
            "enabled": self.enabled,
            "mission_statuses": self.mission_statuses,
            "priority_filter": self.priority_filter.value if self.priority_filter else None,
            "created_at": self.created_at,
        }


@dataclass
class NotificationPayload:
    """Notification content payload"""
    mission_id: str
    user_id: str
    status: str  # DONE, FAILED, etc.
    title: str
    result: str = ""
    error: str = ""
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    
    def to_message(self) -> str:
        """Convert payload to human-readable message"""
        emoji = {
            "DONE": "✅",
            "FAILED": "❌",
            "CANCELLED": "⛔",
            "COMPLETED": "✅",
        }.get(self.status, "ℹ️")
        
        msg = f"{emoji} **Mission {self.status}**\n\n"
        msg += f"**ID:** `{self.mission_id}`\n"
        msg += f"**Title:** {self.title}\n\n"
        
        if self.status == "DONE" and self.result:
            msg += f"**Result:**\n{self.result[:500]}\n"
        elif self.status == "FAILED" and self.error:
            msg += f"**Error:**\n{self.error[:500]}\n"
        
        if self.metadata:
            msg += f"\n**Details:** {str(self.metadata)[:200]}\n"
        
        return msg.strip()
