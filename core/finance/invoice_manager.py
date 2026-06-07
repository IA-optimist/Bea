"""
BEA MAX — Invoice Manager
================================
Manages invoice lifecycle: create → approve → send → track.

All invoice creation starts as DRAFT — requires approval before sending.
Integrates with approval_notifier for Telegram approval gates.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field


@dataclass
class Invoice:
    """Internal invoice tracking record."""
    invoice_id: str = ""
    stripe_invoice_id: str = ""
    customer_id: str = ""
    customer_email: str = ""
    items: list[dict] = field(default_factory=list)
    total_cents: int = 0
    currency: str = "eur"
    status: str = "draft"       # draft, pending_approval, approved, sent, paid, failed, canceled
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None
    sent_at: float | None = None
    paid_at: float | None = None

    def __post_init__(self):
        if not self.invoice_id:
            self.invoice_id = f"inv-{hashlib.sha256(os.urandom(8)).hexdigest()[:10]}"

    def to_dict(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "stripe_id": self.stripe_invoice_id,
            "customer": self.customer_id,
            "email": self.customer_email,
            "items": len(self.items),
            "total": round(self.total_cents / 100, 2),
            "currency": self.currency,
            "status": self.status,
            "created_at": self.created_at,
        }


class InvoiceManager:
    """
    Invoice lifecycle manager.
    
    All invoices start as draft. Sending requires approval.
    """

    def __init__(self, approval_notifier=None):
        self._invoices: dict[str, Invoice] = {}
        self._notifier = approval_notifier

    def create_draft(self, customer_id: str, customer_email: str,
                      items: list[dict], currency: str = "eur") -> Invoice:
        """Create a draft invoice."""
        total = sum(item.get("amount_cents", 0) * item.get("quantity", 1) for item in items)
        invoice = Invoice(
            customer_id=customer_id,
            customer_email=customer_email,
            items=items,
            total_cents=total,
            currency=currency,
            status="draft",
        )
        self._invoices[invoice.invoice_id] = invoice
        return invoice

    def request_approval(self, invoice_id: str) -> str | None:
        """Request approval to send an invoice. Returns ticket_id."""
        invoice = self._invoices.get(invoice_id)
        if not invoice or invoice.status != "draft":
            return None

        invoice.status = "pending_approval"

        if self._notifier:
            ticket = self._notifier.request_approval(
                action="Send invoice",
                module_type="finance",
                module_id=invoice_id,
                module_name=f"Invoice {invoice.total_cents/100:.2f} {invoice.currency.upper()} → {invoice.customer_email}",
                risk_level="medium",
                reason=f"{len(invoice.items)} items, total {invoice.total_cents/100:.2f} {invoice.currency.upper()}",
            )
            return ticket.ticket_id
        return None

    def approve(self, invoice_id: str) -> bool:
        """Approve an invoice for sending."""
        invoice = self._invoices.get(invoice_id)
        if not invoice or invoice.status != "pending_approval":
            return False
        invoice.status = "approved"
        invoice.approved_at = time.time()
        return True

    def mark_sent(self, invoice_id: str, stripe_invoice_id: str = "") -> bool:
        """Mark invoice as sent."""
        invoice = self._invoices.get(invoice_id)
        if not invoice or invoice.status != "approved":
            return False
        invoice.status = "sent"
        invoice.sent_at = time.time()
        if stripe_invoice_id:
            invoice.stripe_invoice_id = stripe_invoice_id
        return True

    def mark_paid(self, invoice_id: str) -> bool:
        """Mark invoice as paid."""
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            return False
        invoice.status = "paid"
        invoice.paid_at = time.time()
        return True

    def cancel(self, invoice_id: str) -> bool:
        """Cancel an invoice."""
        invoice = self._invoices.get(invoice_id)
        if not invoice or invoice.status in ("paid", "canceled"):
            return False
        invoice.status = "canceled"
        return True

    def get(self, invoice_id: str) -> Invoice | None:
        return self._invoices.get(invoice_id)

    def list_invoices(self, status: str = "") -> list[dict]:
        invoices = list(self._invoices.values())
        if status:
            invoices = [i for i in invoices if i.status == status]
        return [i.to_dict() for i in sorted(invoices, key=lambda i: i.created_at, reverse=True)]
