"""email_connector — envoi/lecture d'emails via SMTP/IMAP (stdlib, sans dépendance).

Inerte sans configuration (`is_configured` lit EMAIL_SMTP_HOST / EMAIL_IMAP_HOST /
EMAIL_USER / EMAIL_PASSWORD). Désactivable via CONNECTOR_EMAIL_ENABLED=0.

Actions :
  send       : envoie un email (to, subject, body)
  list_unread: liste les emails non lus (sujet + expéditeur)
"""
from __future__ import annotations

import os

from .base import ConnectorBase, ConnectorResult


class EmailConnector(ConnectorBase):
    name = "email"
    description = "Envoi/lecture d'emails via SMTP/IMAP"
    actions = ["send", "list_unread"]

    def is_configured(self) -> bool:
        return bool(os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASSWORD")
                    and (os.getenv("EMAIL_SMTP_HOST") or os.getenv("EMAIL_IMAP_HOST")))

    def execute(self, action: str, params: dict) -> ConnectorResult:
        result = ConnectorResult(connector=self.name, action=action)
        if action == "send":
            return self._send(params, result)
        if action == "list_unread":
            return self._list_unread(params, result)
        result.error = f"Unknown action: {action}"
        return result

    def _send(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        import smtplib
        from email.message import EmailMessage

        to = params.get("to", "")
        if not to:
            result.error = "'to' requis"
            return result
        host = os.getenv("EMAIL_SMTP_HOST", "")
        port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        user = os.getenv("EMAIL_USER", "")
        pwd = os.getenv("EMAIL_PASSWORD", "")
        if not host or not user:
            result.error = "SMTP non configuré"
            return result

        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = to
        msg["Subject"] = params.get("subject", "(sans objet)")
        msg.set_content(params.get("body", ""))
        try:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls()
                s.login(user, pwd)
                s.send_message(msg)
            result.success = True
            result.output = {"to": to}
        except Exception as e:
            result.error = str(e)[:200]
        return result

    def _list_unread(self, params: dict, result: ConnectorResult) -> ConnectorResult:
        import imaplib
        import email as _email

        host = os.getenv("EMAIL_IMAP_HOST", "")
        user = os.getenv("EMAIL_USER", "")
        pwd = os.getenv("EMAIL_PASSWORD", "")
        limit = int(params.get("limit", 10))
        if not host or not user:
            result.error = "IMAP non configuré"
            return result
        try:
            box = imaplib.IMAP4_SSL(host)
            box.login(user, pwd)
            box.select("INBOX")
            _typ, data = box.search(None, "UNSEEN")
            ids = data[0].split()[-limit:] if data and data[0] else []
            items = []
            for mid in reversed(ids):
                _t, msg_data = box.fetch(mid, "(RFC822)")
                m = _email.message_from_bytes(msg_data[0][1])
                items.append({"from": str(m.get("From", ""))[:120],
                              "subject": str(m.get("Subject", ""))[:160]})
            box.logout()
            result.success = True
            result.output = {"count": len(items), "items": items}
        except Exception as e:
            result.error = str(e)[:200]
        return result
