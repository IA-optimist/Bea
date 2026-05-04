"""
connectors/http_connector.py — Safe HTTP operations (webhooks, notifications).

Actions:
  call_webhook: POST to a configured webhook URL
  send_notification: Send a notification (webhook or log)
"""
from __future__ import annotations

import json
import os
from .base import ConnectorBase, ConnectorResult


class HttpConnector(ConnectorBase):
    name = "http"
    description = "Safe HTTP webhook and notification operations"
    actions = ["call_webhook", "send_notification"]

    def is_configured(self) -> bool:
        """Configured if any webhook URL is set."""
        return bool(
            os.environ.get("WEBHOOK_URL") or
            os.environ.get("N8N_WEBHOOK_URL") or
            os.environ.get("NOTIFICATION_WEBHOOK_URL")
        )

    def execute(self, action: str, params: dict) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)

        if action == "call_webhook":
            return self._call_webhook(params, result)
        elif action == "send_notification":
            return self._send_notification(params, result)
        else:
            result.error = f"Unknown action: {action}"
            return result

    def _call_webhook(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        url = params.get("url", os.environ.get("WEBHOOK_URL", ""))
        payload = params.get("payload", {})
        method = params.get("method", "POST").upper()

        if not url:
            result.error = "No webhook URL provided or configured"
            return result

        # Safety: only allow http/https
        if not url.startswith(("http://", "https://")):
            result.error = "URL must use http or https"
            return result

        try:
            import urllib.request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data if method == "POST" else None,
                headers={"Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")[:1000]
                result.success = resp.status < 400
                result.output = {"status": resp.status, "body": body[:500]}
                if not result.success:
                    result.error = f"HTTP {resp.status}"
        except Exception as e:
            result.error = str(e)[:200]

        return result

    def _send_notification(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        message = params.get("message", "")
        channel = params.get("channel", "log")

        if not message:
            result.error = "message required"
            return result

        if channel == "webhook":
            url = os.environ.get("NOTIFICATION_WEBHOOK_URL", "")
            if url:
                return self._call_webhook({"url": url, "payload": {"text": message}}, result)
            else:
                result.error = "NOTIFICATION_WEBHOOK_URL not configured"
                return result
        else:
            # Default: log notification
            import structlog
            structlog.get_logger("notification").info("notification_sent", message=message[:200])
            result.success = True
            result.output = {"channel": "log", "message": message[:200]}
            return result
