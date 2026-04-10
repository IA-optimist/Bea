"""
Telegram notification client
Sends notifications via Telegram Bot API
"""
from __future__ import annotations
import os
import aiohttp
import structlog
from typing import Optional
from .models import NotificationPayload

log = structlog.get_logger()


class TelegramNotificationClient:
    """
    Telegram Bot notification client
    Uses Telegram Bot API to send messages
    
    Configuration via environment variables:
    - TELEGRAM_BOT_TOKEN: Bot token from @BotFather
    """
    
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.enabled = bool(self.bot_token)
        
        if not self.enabled:
            log.warning("telegram_notifications_disabled",
                        reason="TELEGRAM_BOT_TOKEN not configured")
    
    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Send notification via Telegram
        
        Args:
            destination: Telegram chat_id (user ID or channel ID)
            payload: NotificationPayload with message content
        
        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            log.debug("telegram_notification_skipped", reason="not_enabled")
            return False
        
        try:
            message = self._format_message(payload)
            
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/sendMessage"
                data = {
                    "chat_id": destination,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                }
                
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        log.info("telegram_notification_sent",
                                 chat_id=destination,
                                 mission_id=payload.mission_id)
                        return True
                    else:
                        error_text = await response.text()
                        log.error("telegram_api_error",
                                  status=response.status,
                                  error=error_text[:200],
                                  chat_id=destination)
                        return False
        
        except aiohttp.ClientError as e:
            log.error("telegram_network_error",
                      error=str(e),
                      mission_id=payload.mission_id)
            return False
        except Exception as e:
            log.error("telegram_send_error",
                      error=str(e),
                      mission_id=payload.mission_id)
            return False
    
    def _format_message(self, payload: NotificationPayload) -> str:
        """Format notification payload as Telegram message"""
        emoji = {
            "DONE": "✅",
            "FAILED": "❌",
            "CANCELLED": "⛔",
            "COMPLETED": "✅",
        }.get(payload.status, "ℹ️")
        
        msg = f"{emoji} *Mission {payload.status}*\n\n"
        msg += f"*ID:* `{payload.mission_id}`\n"
        msg += f"*Goal:* {self._escape_markdown(payload.title)}\n\n"
        
        if payload.status in ("DONE", "COMPLETED") and payload.result:
            result_preview = payload.result[:300]
            if len(payload.result) > 300:
                result_preview += "..."
            msg += f"*Result:*\n{self._escape_markdown(result_preview)}\n"
        
        elif payload.status == "FAILED" and payload.error:
            error_preview = payload.error[:300]
            if len(payload.error) > 300:
                error_preview += "..."
            msg += f"*Error:*\n{self._escape_markdown(error_preview)}\n"
        
        return msg.strip()
    
    def _escape_markdown(self, text: str) -> str:
        """Escape special Markdown characters for Telegram"""
        # Telegram Markdown V1 special chars
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        escaped = text
        for char in special_chars:
            escaped = escaped.replace(char, f"\\{char}")
        return escaped
    
    async def send_test_message(self, chat_id: str) -> bool:
        """Send test message to verify configuration"""
        test_payload = NotificationPayload(
            mission_id="test-notification",
            user_id="test",
            status="DONE",
            title="Test Notification from JarvisMax",
            result="If you see this message, Telegram notifications are working correctly!",
        )
        return await self.send(chat_id, test_payload)
