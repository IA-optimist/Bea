"""
Integration du Webhook Alertmanager dans l'API FastAPI BeaMax

Ce fichier montre comment intégrer le webhook Alertmanager dans votre API.
Copiez le code nécessaire dans votre fichier main.py ou créez un nouveau router.
"""

import os
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Query
import httpx
import logging

logger = logging.getLogger(__name__)

# Router pour les webhooks
webhook_router = APIRouter(prefix="/api/v2/webhooks", tags=["webhooks"])


class TelegramNotifier:
    """Envoyer des notifications Telegram depuis les alertes Alertmanager"""
    
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            logger.info("Telegram notifications enabled")
        else:
            logger.warning("Telegram notifications disabled - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID not set")
    
    def format_alert_message(self, alert: Dict[str, Any]) -> str:
        """Formatter une alerte en message Telegram"""
        status = alert.get('status', 'unknown').upper()
        labels = alert.get('labels', {})
        annotations = alert.get('annotations', {})
        
        # Emoji selon la sévérité
        severity = labels.get('severity', 'info')
        emoji_map = {
            'critical': '🔴',
            'warning': '⚠️',
            'info': 'ℹ️'
        }
        emoji = emoji_map.get(severity, '📊')
        
        # Construire le message
        lines = [
            f"{emoji} <b>ALERT: {status}</b>",
            "",
            f"📋 <b>Alert:</b> {labels.get('alertname', 'Unknown')}",
            f"🏷️ <b>Severity:</b> {severity.upper()}",
            f"🔧 <b>Component:</b> {labels.get('component', 'Unknown')}",
            "",
        ]
        
        # Ajouter summary et description
        if summary := annotations.get('summary'):
            lines.append(f"📌 {summary}")
        
        if description := annotations.get('description'):
            lines.append(f"📝 {description}")
        
        # Ajouter instance
        if instance := labels.get('instance'):
            lines.append(f"🖥️ <b>Instance:</b> {instance}")
        
        # Ajouter timestamps
        if starts_at := alert.get('startsAt'):
            lines.append(f"⏰ <b>Started:</b> {starts_at}")
        
        if status == 'RESOLVED' and (ends_at := alert.get('endsAt')):
            lines.append(f"✅ <b>Resolved:</b> {ends_at}")
        
        return "\n".join(lines)
    
    async def send_alert(self, alert: Dict[str, Any]) -> bool:
        """Envoyer une alerte à Telegram"""
        if not self.enabled:
            logger.debug("Telegram not configured, skipping alert")
            return False
        
        try:
            message = self.format_alert_message(alert)
            api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    api_url,
                    json={
                        'chat_id': self.chat_id,
                        'text': message,
                        'parse_mode': 'HTML',
                        'disable_web_page_preview': True
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    logger.info(f"Alert sent to Telegram: {alert.get('labels', {}).get('alertname')}")
                    return True
                else:
                    logger.error(f"Failed to send to Telegram: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
            return False


# Instance globale
telegram_notifier = TelegramNotifier()


@webhook_router.post("/alertmanager")
async def alertmanager_webhook(
    request: Request,
    priority: Optional[str] = Query(default="default", description="Priority: default, critical, info")
):
    """
    Webhook pour recevoir les alertes d'Alertmanager et les transférer à Telegram
    
    Alertmanager envoie un payload JSON avec la structure:
    {
        "version": "4",
        "groupKey": "...",
        "status": "firing",
        "receiver": "telegram-alerts",
        "groupLabels": {...},
        "commonLabels": {...},
        "commonAnnotations": {...},
        "externalURL": "...",
        "alerts": [
            {
                "status": "firing",
                "labels": {...},
                "annotations": {...},
                "startsAt": "...",
                "endsAt": "...",
                "generatorURL": "...",
                "fingerprint": "..."
            }
        ]
    }
    """
    try:
        payload = await request.json()
        alerts = payload.get('alerts', [])
        
        logger.info(f"Received {len(alerts)} alerts from Alertmanager (priority: {priority})")
        
        # Log des alertes pour debug
        for alert in alerts:
            logger.debug(f"Alert: {alert.get('labels', {}).get('alertname')} - {alert.get('status')}")
        
        # Envoyer à Telegram
        results = []
        for alert in alerts:
            success = await telegram_notifier.send_alert(alert)
            results.append(success)
        
        return {
            "status": "success",
            "priority": priority,
            "alerts_received": len(alerts),
            "alerts_sent": sum(results),
            "telegram_enabled": telegram_notifier.enabled
        }
        
    except Exception as e:
        logger.error(f"Error processing alertmanager webhook: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@webhook_router.get("/test-telegram")
async def test_telegram():
    """
    Test endpoint pour vérifier que Telegram fonctionne
    
    Usage: curl http://localhost:8000/api/v2/webhooks/test-telegram
    """
    if not telegram_notifier.enabled:
        return {
            "status": "error",
            "message": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        }
    
    # Créer une alerte de test
    test_alert = {
        "status": "firing",
        "labels": {
            "alertname": "TestAlert",
            "severity": "info",
            "component": "test",
            "instance": "vps1"
        },
        "annotations": {
            "summary": "This is a test alert",
            "description": "Testing Telegram integration for BeaMax monitoring"
        },
        "startsAt": "2026-04-09T21:00:00Z"
    }
    
    success = await telegram_notifier.send_alert(test_alert)
    
    return {
        "status": "success" if success else "error",
        "message": "Test alert sent to Telegram" if success else "Failed to send test alert",
        "telegram_configured": telegram_notifier.enabled
    }


# ============================================
# INTEGRATION DANS VOTRE API
# ============================================

"""
Pour intégrer ce code dans votre API BeaMax:

1. Ajouter dans main.py ou créer un nouveau fichier api/webhooks.py:

    from deploy.monitoring.api_webhook_integration import webhook_router  # exemple : copier dans api/
    
    # Dans votre app FastAPI
    app.include_router(webhook_router)

2. Ou copier directement le code du router dans votre structure existante

3. Ajouter dans .env:
    TELEGRAM_BOT_TOKEN=votre_token_ici
    TELEGRAM_CHAT_ID=votre_chat_id_ici

4. Redémarrer l'API:
    docker compose restart api

5. Tester:
    curl http://localhost:8000/api/v2/webhooks/test-telegram

6. Vérifier les logs:
    docker logs beamax-api -f
"""


# ============================================
# ALTERNATIVE: Intégration Simple
# ============================================

"""
Si vous voulez une intégration plus simple, ajoutez juste ceci dans main.py:

@app.post("/api/v2/webhooks/alertmanager")
async def alertmanager_webhook(request: Request):
    '''Receive alerts from Alertmanager'''
    payload = await request.json()
    alerts = payload.get('alerts', [])
    
    # Log les alertes
    for alert in alerts:
        status = alert.get('status')
        alertname = alert.get('labels', {}).get('alertname')
        severity = alert.get('labels', {}).get('severity')
        logger.warning(f"Alert [{severity}] {alertname}: {status}")
    
    return {"status": "success", "alerts_received": len(alerts)}

Ceci logge simplement les alertes dans les logs de l'API.
Pour l'intégration Telegram complète, utilisez le code complet ci-dessus.
"""
