"""api_connectors — connecteurs HTTP prêts à l'emploi (Slack, Telegram, Discord, Notion).

Tous partagent `_HttpConnector` (un seul chemin réseau `_http_request`, mockable en
test). Chacun est **inerte sans credentials** (`is_configured` lit les variables
d'env), et désactivable via `CONNECTOR_<NAME>_ENABLED=0`. Aucune dépendance nouvelle
(`requests` est déjà requis ; import paresseux).
"""
from __future__ import annotations

import os

from .base import ConnectorBase, ConnectorResult


def _http_request(method: str, url: str, headers: dict | None = None,
                  json_body: dict | None = None, timeout: int = 15) -> tuple[int, str]:
    """Point réseau unique (mocké en test). Renvoie (status_code, body tronqué)."""
    import httpx
    resp = httpx.request(method, url, headers=headers or {}, json=json_body, timeout=timeout)
    return resp.status_code, (resp.text or "")[:1000]


class _HttpConnector(ConnectorBase):
    """Base pour connecteurs basés HTTP/JSON."""

    def _send(self, method: str, url: str, action: str, headers: dict | None = None,
              json_body: dict | None = None) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)
        try:
            status, body = _http_request(method, url, headers=headers, json_body=json_body)
            result.success = 200 <= status < 300
            result.output = {"status": status, "body": body}
            if not result.success:
                result.error = f"http_{status}: {body[:200]}"
        except Exception as e:
            result.error = str(e)[:200]
        return result


class SlackConnector(_HttpConnector):
    name = "slack"
    description = "Envoi de messages Slack (Incoming Webhook)"
    actions = ["send_message"]

    def is_configured(self) -> bool:
        return bool(os.getenv("SLACK_WEBHOOK_URL"))

    def execute(self, action: str, params: dict) -> ConnectorResult:
        if action != "send_message":
            return ConnectorResult(connector=self.name, action=action, error=f"Unknown action: {action}")
        url = os.getenv("SLACK_WEBHOOK_URL", "")
        if not url:
            return ConnectorResult(connector=self.name, action=action, error="SLACK_WEBHOOK_URL manquant")
        return self._send("POST", url, action, json_body={"text": params.get("text", "")})


class TelegramConnector(_HttpConnector):
    name = "telegram"
    description = "Envoi de messages Telegram (Bot API)"
    actions = ["send_message"]

    def is_configured(self) -> bool:
        return bool(os.getenv("TELEGRAM_BOT_TOKEN"))

    def execute(self, action: str, params: dict) -> ConnectorResult:
        if action != "send_message":
            return ConnectorResult(connector=self.name, action=action, error=f"Unknown action: {action}")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = params.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return ConnectorResult(connector=self.name, action=action, error="token/chat_id manquant")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return self._send("POST", url, action,
                          json_body={"chat_id": chat_id, "text": params.get("text", "")})


class DiscordConnector(_HttpConnector):
    name = "discord"
    description = "Envoi de messages Discord (Webhook)"
    actions = ["send_message"]

    def is_configured(self) -> bool:
        return bool(os.getenv("DISCORD_WEBHOOK_URL"))

    def execute(self, action: str, params: dict) -> ConnectorResult:
        if action != "send_message":
            return ConnectorResult(connector=self.name, action=action, error=f"Unknown action: {action}")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if not url:
            return ConnectorResult(connector=self.name, action=action, error="DISCORD_WEBHOOK_URL manquant")
        return self._send("POST", url, action, json_body={"content": params.get("text", "")})


class NotionConnector(_HttpConnector):
    name = "notion"
    description = "Création de pages Notion (API officielle)"
    actions = ["create_page"]

    def is_configured(self) -> bool:
        return bool(os.getenv("NOTION_TOKEN"))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {os.getenv('NOTION_TOKEN', '')}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    def execute(self, action: str, params: dict) -> ConnectorResult:
        if action != "create_page":
            return ConnectorResult(connector=self.name, action=action, error=f"Unknown action: {action}")
        db_id = params.get("database_id") or os.getenv("NOTION_DATABASE_ID", "")
        title = params.get("title", "")
        if not os.getenv("NOTION_TOKEN") or not db_id:
            return ConnectorResult(connector=self.name, action=action, error="NOTION_TOKEN/database_id manquant")
        body = {
            "parent": {"database_id": db_id},
            "properties": {"Name": {"title": [{"text": {"content": title}}]}},
        }
        return self._send("POST", "https://api.notion.com/v1/pages", action,
                          headers=self._headers(), json_body=body)
