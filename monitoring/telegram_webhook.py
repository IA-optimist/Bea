#!/usr/bin/env python3
"""
Telegram Webhook for Alertmanager Notifications
This script can be integrated into the FastAPI app or run standalone
"""

import os
import asyncio
from datetime import datetime
from typing import Dict, Any, List
import httpx


class TelegramAlertManager:
    """Handle Alertmanager alerts and send to Telegram"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def format_alert(self, alert: Dict[str, Any]) -> str:
        """Format alert data into readable message"""
        status = alert.get('status', 'unknown').upper()
        labels = alert.get('labels', {})
        annotations = alert.get('annotations', {})
        
        # Emoji based on severity
        severity = labels.get('severity', 'info')
        emoji_map = {
            'critical': '🔴',
            'warning': '⚠️',
            'info': 'ℹ️'
        }
        emoji = emoji_map.get(severity, '📊')
        
        # Build message
        message_parts = [
            f"{emoji} ALERT: {status}",
            f"",
            f"📋 Alert: {labels.get('alertname', 'Unknown')}",
            f"🏷️ Severity: {severity.upper()}",
            f"🔧 Component: {labels.get('component', 'Unknown')}",
            f"",
        ]
        
        # Add summary and description
        if summary := annotations.get('summary'):
            message_parts.append(f"📌 {summary}")
        
        if description := annotations.get('description'):
            message_parts.append(f"📝 {description}")
        
        # Add instance info
        if instance := labels.get('instance'):
            message_parts.append(f"🖥️ Instance: {instance}")
        
        # Add timestamps
        if starts_at := alert.get('startsAt'):
            message_parts.append(f"⏰ Started: {starts_at}")
        
        if status == 'RESOLVED' and (ends_at := alert.get('endsAt')):
            message_parts.append(f"✅ Resolved: {ends_at}")
        
        return "\n".join(message_parts)
    
    async def send_message(self, message: str) -> bool:
        """Send message to Telegram"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    json={
                        'chat_id': self.chat_id,
                        'text': message,
                        'parse_mode': 'HTML',
                        'disable_web_page_preview': True
                    },
                    timeout=10.0
                )
                return response.status_code == 200
        except Exception as e:
            print(f"Error sending telegram message: {e}")
            return False
    
    async def process_webhook(self, payload: Dict[str, Any], priority: str = 'default') -> List[bool]:
        """Process Alertmanager webhook payload"""
        alerts = payload.get('alerts', [])
        results = []
        
        # Add header for multiple alerts
        if len(alerts) > 1:
            header = f"📬 Batch Alert ({len(alerts)} alerts) - Priority: {priority.upper()}\n"
            await self.send_message(header)
        
        # Send each alert
        for alert in alerts:
            message = self.format_alert(alert)
            success = await self.send_message(message)
            results.append(success)
            
            # Small delay to avoid rate limiting
            if len(alerts) > 1:
                await asyncio.sleep(0.5)
        
        return results


# FastAPI integration example
"""
from fastapi import FastAPI, Request, Query
from typing import Optional

app = FastAPI()

# Initialize from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    telegram_manager = TelegramAlertManager(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
else:
    telegram_manager = None

@app.post("/api/v2/webhooks/alertmanager")
async def alertmanager_webhook(
    request: Request,
    priority: Optional[str] = Query(default="default")
):
    '''Receive alerts from Alertmanager and forward to Telegram'''
    if not telegram_manager:
        return {"status": "error", "message": "Telegram not configured"}
    
    payload = await request.json()
    results = await telegram_manager.process_webhook(payload, priority)
    
    return {
        "status": "success",
        "alerts_sent": len(results),
        "success_count": sum(results)
    }
"""


# Standalone test
async def test_webhook():
    """Test the webhook with sample data"""
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')
    
    manager = TelegramAlertManager(bot_token, chat_id)
    
    # Sample alert payload
    sample_payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighCPUUsage",
                    "severity": "warning",
                    "component": "system",
                    "instance": "vps1"
                },
                "annotations": {
                    "summary": "High CPU usage detected",
                    "description": "CPU usage is 85% on vps1"
                },
                "startsAt": datetime.utcnow().isoformat()
            }
        ]
    }
    
    results = await manager.process_webhook(sample_payload, "test")
    print(f"Test results: {results}")


if __name__ == "__main__":
    asyncio.run(test_webhook())
