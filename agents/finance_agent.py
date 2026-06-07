"""
BEA MAX — Finance Agent
==============================
Autonomous finance operations with mandatory approval gates.

Capabilities:
  - Product/price setup
  - Subscription management
  - Invoice creation
  - Payment link generation
  - Revenue tracking
  - Basic P&L estimation

Safety rules:
  - NEVER execute payments without approval
  - NEVER modify existing subscriptions silently
  - NEVER refund without approval
  - NEVER change pricing without approval
  - API key ONLY from vault
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from tools.integrations.stripe_tool import StripeTool, StripeResponse
from core.finance.finance_memory import (
    FinanceMemory, FinancialEvent, CustomerRecord, SubscriptionRecord,
)
from core.finance.revenue_tracker import RevenueTracker
from core.finance.invoice_manager import InvoiceManager

logger = logging.getLogger(__name__)


# Actions requiring approval
APPROVAL_REQUIRED = frozenset({
    "create_payment_link",
    "create_subscription",
    "cancel_subscription",
    "send_invoice",
    "change_price",
    "refund",
    "delete_customer",
    "large_discount",      # discount > 30%
})

# Actions that are safe to auto-execute
SAFE_ACTIONS = frozenset({
    "create_product",
    "create_price",
    "create_customer",
    "list_products",
    "list_customers",
    "list_subscriptions",
    "retrieve_balance",
    "retrieve_payment_status",
    "revenue_summary",
})


@dataclass
class FinanceAction:
    """A requested financial action."""
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    approval_ticket: str = ""
    approved: bool = False
    result: StripeResponse | None = None
    error: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "approval_required": self.approval_required,
            "approved": self.approved,
            "result": self.result.safe_dict() if self.result else None,
            "error": self.error[:200],
        }


class FinanceAgent:
    """
    Finance agent with approval gates.
    
    Usage:
        agent = FinanceAgent(stripe=StripeTool(api_key=os.environ.get("STRIPE_API_KEY", "")))
        result = agent.create_product("My SaaS", "AI tool")
        # Auto-executes (safe action)
        
        result = agent.create_payment_link("price_xxx")
        # Returns approval_required=True, sends Telegram notification
        
        agent.approve_action(action_id)
        # Executes after approval
    """

    def __init__(
        self,
        stripe: StripeTool | None = None,
        memory: FinanceMemory | None = None,
        approval_notifier=None,
        vault=None,
    ):
        self._stripe = stripe or StripeTool(vault=vault)
        self._memory = memory or FinanceMemory()
        self._tracker = RevenueTracker(self._memory)
        self._invoices = InvoiceManager(approval_notifier=approval_notifier)
        self._notifier = approval_notifier
        self._pending: dict[str, FinanceAction] = {}
        self._audit: list[dict] = []

    # ═══════════════════════════════════════════════════════════════
    # SAFE ACTIONS (no approval needed)
    # ═══════════════════════════════════════════════════════════════

    def create_product(self, name: str, description: str = "") -> FinanceAction:
        """Create a product (safe — no payment involved)."""
        action = FinanceAction(action="create_product", params={"name": name})
        result = self._stripe.create_product(name, description)
        action.result = result
        self._log_audit("create_product", result)
        return action

    def create_price(self, product_id: str, amount_cents: int,
                      currency: str = "eur", interval: str | None = None) -> FinanceAction:
        """Create a price (safe — no charge)."""
        action = FinanceAction(action="create_price", params={"product": product_id, "amount": amount_cents})
        result = self._stripe.create_price(product_id, amount_cents, currency, interval)
        action.result = result
        self._log_audit("create_price", result)
        return action

    def create_customer(self, email: str, name: str = "") -> FinanceAction:
        """Create a customer (safe)."""
        action = FinanceAction(action="create_customer", params={"email": email})
        result = self._stripe.create_customer(email, name)
        action.result = result
        if result.success:
            self._memory.add_customer(CustomerRecord(
                customer_id=result.stripe_id, email=email, name=name,
            ))
        self._log_audit("create_customer", result)
        return action

    def list_products(self) -> FinanceAction:
        action = FinanceAction(action="list_products")
        action.result = self._stripe.list_products()
        return action

    def list_customers(self) -> FinanceAction:
        action = FinanceAction(action="list_customers")
        action.result = self._stripe.list_customers()
        return action

    def list_subscriptions(self, status: str = "active") -> FinanceAction:
        action = FinanceAction(action="list_subscriptions")
        action.result = self._stripe.list_subscriptions(status)
        return action

    def retrieve_balance(self) -> FinanceAction:
        action = FinanceAction(action="retrieve_balance")
        action.result = self._stripe.retrieve_balance()
        return action

    def revenue_summary(self) -> dict:
        """Get revenue summary (no Stripe call needed)."""
        return self._tracker.snapshot().to_dict()

    # ═══════════════════════════════════════════════════════════════
    # APPROVAL-REQUIRED ACTIONS
    # ═══════════════════════════════════════════════════════════════

    def create_payment_link(self, price_id: str) -> FinanceAction:
        """Request payment link creation (requires approval)."""
        action = FinanceAction(
            action="create_payment_link",
            params={"price_id": price_id},
            approval_required=True,
        )
        ticket = self._request_approval(action, "Create payment link", "medium")
        action.approval_ticket = ticket or ""
        self._pending[action.approval_ticket or f"pending-{time.time()}"] = action
        return action

    def create_subscription(self, customer_id: str, price_id: str,
                             trial_days: int = 0) -> FinanceAction:
        """Request subscription creation (requires approval)."""
        action = FinanceAction(
            action="create_subscription",
            params={"customer_id": customer_id, "price_id": price_id, "trial_days": trial_days},
            approval_required=True,
        )
        ticket = self._request_approval(action, "Create subscription", "high")
        action.approval_ticket = ticket or ""
        self._pending[action.approval_ticket or f"pending-{time.time()}"] = action
        return action

    def cancel_subscription(self, subscription_id: str) -> FinanceAction:
        """Request subscription cancellation (requires approval)."""
        action = FinanceAction(
            action="cancel_subscription",
            params={"subscription_id": subscription_id},
            approval_required=True,
        )
        ticket = self._request_approval(action, "Cancel subscription", "high")
        action.approval_ticket = ticket or ""
        self._pending[action.approval_ticket or f"pending-{time.time()}"] = action
        return action

    def create_invoice(self, customer_id: str, customer_email: str,
                        items: list[dict]) -> FinanceAction:
        """Create a draft invoice (requires approval to send)."""
        action = FinanceAction(
            action="create_invoice",
            params={"customer_id": customer_id, "items": items},
        )
        invoice = self._invoices.create_draft(customer_id, customer_email, items)
        ticket = self._invoices.request_approval(invoice.invoice_id)
        action.approval_required = True
        action.approval_ticket = ticket or ""
        action.result = StripeResponse(
            success=True, object_type="invoice_draft",
            stripe_id=invoice.invoice_id,
            human_readable=f"Draft invoice created: {invoice.total_cents/100:.2f} {invoice.currency.upper()}",
        )
        return action

    # ═══════════════════════════════════════════════════════════════
    # APPROVAL HANDLING
    # ═══════════════════════════════════════════════════════════════

    def approve_action(self, ticket_id: str) -> FinanceAction | None:
        """Execute an approved financial action."""
        action = self._pending.pop(ticket_id, None)
        if not action:
            return None

        action.approved = True
        p = action.params

        if action.action == "create_payment_link":
            action.result = self._stripe.create_payment_link(p["price_id"])
        elif action.action == "create_subscription":
            action.result = self._stripe.create_subscription(
                p["customer_id"], p["price_id"], p.get("trial_days", 0),
            )
            if action.result and action.result.success:
                self._memory.add_subscription(SubscriptionRecord(
                    subscription_id=action.result.stripe_id,
                    customer_id=p["customer_id"],
                    price_id=p["price_id"],
                ))
        elif action.action == "cancel_subscription":
            action.result = self._stripe.cancel_subscription(p["subscription_id"])
            if action.result and action.result.success:
                self._memory.update_subscription_status(p["subscription_id"], "canceled")

        self._log_audit(f"approved_{action.action}", action.result)
        return action

    def deny_action(self, ticket_id: str) -> bool:
        """Deny a pending action."""
        action = self._pending.pop(ticket_id, None)
        if action:
            self._log_audit(f"denied_{action.action}", None)
            return True
        return False

    def get_pending(self) -> list[dict]:
        """List pending approval actions."""
        return [a.to_dict() for a in self._pending.values()]

    # ═══════════════════════════════════════════════════════════════
    # WEBHOOK PROCESSING
    # ═══════════════════════════════════════════════════════════════

    def process_webhook(self, event_type: str, data: dict) -> None:
        """Process a Stripe webhook event."""
        obj = data.get("object", {})
        event = FinancialEvent(
            event_id=data.get("id", ""),
            event_type=event_type,
            stripe_id=obj.get("id", ""),
            customer_id=obj.get("customer", ""),
            amount_cents=obj.get("amount", obj.get("amount_paid", 0)),
            currency=obj.get("currency", "eur"),
            status=obj.get("status", ""),
        )
        self._memory.record_event(event)

        # Update subscription status from webhook
        if event_type == "customer.subscription.created":
            self._memory.add_subscription(SubscriptionRecord(
                subscription_id=obj.get("id", ""),
                customer_id=obj.get("customer", ""),
                status=obj.get("status", "active"),
                amount_cents=obj.get("plan", {}).get("amount", 0),
                interval=obj.get("plan", {}).get("interval", "month"),
            ))
        elif event_type == "customer.subscription.deleted":
            self._memory.update_subscription_status(obj.get("id", ""), "canceled")

    # ═══════════════════════════════════════════════════════════════
    # P&L
    # ═══════════════════════════════════════════════════════════════

    def estimate_pl(self) -> dict:
        """Basic P&L estimation."""
        snapshot = self._tracker.snapshot()
        return {
            "revenue": snapshot.to_dict(),
            "monthly": self._tracker.monthly_revenue(6),
            "growth_rate_pct": self._tracker.growth_rate(),
        }

    # ═══════════════════════════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════════════════════════

    def _request_approval(self, action: FinanceAction, description: str,
                           risk: str) -> str | None:
        if not self._notifier:
            return None
        ticket = self._notifier.request_approval(
            action=description,
            module_type="finance",
            module_id=action.action,
            module_name=description,
            risk_level=risk,
            agent_name="finance_agent",
            reason=str(action.params)[:200],
        )
        return ticket.ticket_id

    def _log_audit(self, action: str, result: StripeResponse | None) -> None:
        entry = {
            "action": action,
            "timestamp": time.time(),
            "success": result.success if result else False,
            "stripe_id": result.stripe_id if result else "",
        }
        self._audit.append(entry)
        if len(self._audit) > 500:
            self._audit = self._audit[-300:]

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._audit))[:limit]
