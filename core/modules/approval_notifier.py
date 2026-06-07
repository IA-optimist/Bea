"""
BEA MAX — Approval Notifier
=================================
Sends approval requests to Telegram and handles callbacks.

When a high-risk action is detected:
1. Create approval request with unique token
2. Send Telegram message with approve/deny buttons
3. Handle callback → update audit log → resume/cancel action

Anti-replay: each approval token is single-use with expiry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT = 300  # 5 minutes


@dataclass
class ApprovalTicket:
    """A pending approval request."""
    ticket_id: str
    action: str
    module_type: str
    module_id: str
    module_name: str
    risk_level: str = "medium"
    agent_name: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0
    status: str = "pending"     # pending / approved / denied / expired
    decided_at: float | None = None
    telegram_message_id: int | None = None

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = self.created_at + APPROVAL_TIMEOUT

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at and self.status == "pending"

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "action": self.action,
            "module": f"{self.module_type}/{self.module_id}",
            "name": self.module_name,
            "risk": self.risk_level,
            "agent": self.agent_name,
            "reason": self.reason[:200],
            "status": "expired" if self.is_expired else self.status,
            "created": self.created_at,
        }


class ApprovalNotifier:
    """
    Manages approval requests with Telegram notifications.
    """

    def __init__(
        self,
        bot_token: str = "",  # nosec B107 — empty default; real value pulled from TELEGRAM_BOT_TOKEN env below.
        chat_id: str = "",  # nosec B107 — same.
    ):
        self._bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self._tickets: dict[str, ApprovalTicket] = {}

    def request_approval(
        self,
        action: str,
        module_type: str,
        module_id: str,
        module_name: str,
        risk_level: str = "medium",
        agent_name: str = "",
        reason: str = "",
    ) -> ApprovalTicket:
        """
        Create an approval request and notify via Telegram.
        Returns the ticket for tracking.
        """
        # Generate unique ticket ID
        ticket_id = hashlib.sha256(
            f"{action}{module_id}{time.time()}{os.urandom(8).hex()}".encode()
        ).hexdigest()[:16]

        ticket = ApprovalTicket(
            ticket_id=ticket_id,
            action=action,
            module_type=module_type,
            module_id=module_id,
            module_name=module_name,
            risk_level=risk_level,
            agent_name=agent_name,
            reason=reason,
        )

        self._tickets[ticket_id] = ticket

        # Send Telegram notification
        if self._bot_token and self._chat_id:
            msg_id = self._send_telegram(ticket)
            ticket.telegram_message_id = msg_id

        return ticket

    def resolve(self, ticket_id: str, decision: str) -> bool:
        """
        Resolve an approval ticket.
        decision: "approved" or "denied"
        Returns True if resolved, False if expired/not found.
        """
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return False

        if ticket.is_expired:
            ticket.status = "expired"
            return False

        if ticket.status != "pending":
            return False  # Already resolved

        ticket.status = decision
        ticket.decided_at = time.time()

        # Update Telegram message
        if self._bot_token and ticket.telegram_message_id:
            self._update_telegram(ticket)

        return True

    def get_ticket(self, ticket_id: str) -> ApprovalTicket | None:
        ticket = self._tickets.get(ticket_id)
        if ticket and ticket.is_expired:
            ticket.status = "expired"
        return ticket

    def list_pending(self) -> list[dict]:
        """List all pending approval tickets."""
        results = []
        for t in self._tickets.values():
            if t.is_expired:
                t.status = "expired"
            if t.status == "pending":
                results.append(t.to_dict())
        return results

    def cleanup_expired(self) -> int:
        """Clean up expired tickets."""
        expired = [tid for tid, t in self._tickets.items() if t.is_expired]
        for tid in expired:
            self._tickets[tid].status = "expired"
        return len(expired)

    def _send_telegram(self, ticket: ApprovalTicket) -> int | None:
        """Send approval request to Telegram with inline buttons."""
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🔴"}.get(ticket.risk_level, "⚪")

        text = (
            f"🔐 *Approval Required*\n\n"
            f"*Action:* {ticket.action}\n"
            f"*Module:* {ticket.module_name}\n"
            f"*Risk:* {risk_emoji} {ticket.risk_level.upper()}\n"
        )
        if ticket.agent_name:
            text += f"*Agent:* {ticket.agent_name}\n"
        if ticket.reason:
            text += f"*Reason:* {ticket.reason[:200]}\n"
        text += f"\n_Expires in {APPROVAL_TIMEOUT // 60} minutes_"

        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{ticket.ticket_id}"},
                {"text": "❌ Deny", "callback_data": f"deny:{ticket.ticket_id}"},
            ]]
        }

        try:
            payload = json.dumps({
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            }).encode()

            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
                data = json.loads(resp.read())
                if data.get("ok"):
                    return data["result"]["message_id"]
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

        return None

    def _update_telegram(self, ticket: ApprovalTicket) -> None:
        """Update the Telegram message to show resolution."""
        status_text = "✅ APPROVED" if ticket.status == "approved" else "❌ DENIED"
        text = (
            f"🔐 *Approval {status_text}*\n\n"
            f"*Action:* {ticket.action}\n"
            f"*Module:* {ticket.module_name}\n"
            f"*Decision:* {status_text}\n"
        )

        try:
            payload = json.dumps({
                "chat_id": self._chat_id,
                "message_id": ticket.telegram_message_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode()

            url = f"https://api.telegram.org/bot{self._bot_token}/editMessageText"
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)  # nosec B310 — URL pre-validated upstream (scheme/host allowlist or trusted config)
        except Exception as e:
            logger.error(f"Telegram update failed: {e}")

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tickets.values() if t.status == "pending" and not t.is_expired)
