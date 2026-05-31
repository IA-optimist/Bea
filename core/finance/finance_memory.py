"""
JARVIS MAX — Finance Memory
===============================
Stores financial events, subscriptions, and customer data safely.

Safety:
  - No card numbers ever stored
  - No full addresses
  - No secret keys
  - Customer data: id + email + name only
  - Financial amounts: safe integers (cents)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
log = logger  # M3 emitter alias


@dataclass
class FinancialEvent:
    """A single financial event."""
    event_id: str = ""
    event_type: str = ""        # payment_succeeded, subscription_created, etc.
    stripe_id: str = ""
    customer_id: str = ""
    amount_cents: int = 0
    currency: str = "eur"
    status: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "type": self.event_type,
            "stripe_id": self.stripe_id,
            "customer": self.customer_id,
            "amount": self.amount_cents,
            "currency": self.currency,
            "status": self.status,
            "timestamp": self.timestamp,
        }


@dataclass
class CustomerRecord:
    """Minimal customer record (no sensitive data)."""
    customer_id: str
    email: str = ""
    name: str = ""
    created_at: float = field(default_factory=time.time)
    subscription_ids: list[str] = field(default_factory=list)
    total_paid_cents: int = 0
    payment_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.customer_id, "email": self.email, "name": self.name,
            "subscriptions": len(self.subscription_ids),
            "total_paid": self.total_paid_cents,
            "payments": self.payment_count,
        }


@dataclass
class SubscriptionRecord:
    """Subscription tracking record."""
    subscription_id: str
    customer_id: str = ""
    price_id: str = ""
    product_id: str = ""
    status: str = "active"
    amount_cents: int = 0
    currency: str = "eur"
    interval: str = "month"
    created_at: float = field(default_factory=time.time)
    canceled_at: float | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ("active", "trialing")

    @property
    def mrr_cents(self) -> int:
        """Monthly recurring revenue in cents."""
        if not self.is_active:
            return 0
        if self.interval == "year":
            return self.amount_cents // 12
        return self.amount_cents

    def to_dict(self) -> dict:
        return {
            "id": self.subscription_id, "customer": self.customer_id,
            "status": self.status, "amount": self.amount_cents,
            "currency": self.currency, "interval": self.interval,
            "mrr_cents": self.mrr_cents,
        }


class FinanceMemory:
    """
    In-memory financial data store with optional JSON persistence.
    
    Stores events, customers, and subscriptions.
    Never stores card data, full addresses, or secrets.
    """

    MAX_EVENTS = 1000

    def __init__(self, persist_path: str = ""):
        self._path = Path(persist_path) if persist_path else None
        self._events: list[FinancialEvent] = []
        self._customers: dict[str, CustomerRecord] = {}
        self._subscriptions: dict[str, SubscriptionRecord] = {}
        self._load()

    # ── Events ──

    def record_event(self, event: FinancialEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.MAX_EVENTS:
            self._events = self._events[-self.MAX_EVENTS:]
        # Update customer totals
        if event.customer_id and event.event_type == "payment_succeeded":
            cust = self._customers.get(event.customer_id)
            if cust:
                cust.total_paid_cents += event.amount_cents
                cust.payment_count += 1
        self._save()

    def get_events(self, event_type: str = "", limit: int = 50) -> list[dict]:
        events = self._events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in reversed(events)][:limit]

    # ── Customers ──

    def add_customer(self, customer: CustomerRecord) -> None:
        self._customers[customer.customer_id] = customer
        self._save()

    def get_customer(self, customer_id: str) -> CustomerRecord | None:
        return self._customers.get(customer_id)

    def list_customers(self) -> list[dict]:
        return [c.to_dict() for c in self._customers.values()]

    @property
    def customer_count(self) -> int:
        return len(self._customers)

    # ── Subscriptions ──

    def add_subscription(self, sub: SubscriptionRecord) -> None:
        self._subscriptions[sub.subscription_id] = sub
        # Link to customer
        cust = self._customers.get(sub.customer_id)
        if cust and sub.subscription_id not in cust.subscription_ids:
            cust.subscription_ids.append(sub.subscription_id)
        self._save()

    def update_subscription_status(self, sub_id: str, status: str) -> None:
        sub = self._subscriptions.get(sub_id)
        if sub:
            sub.status = status
            if status == "canceled":
                sub.canceled_at = time.time()
            self._save()

    def get_subscription(self, sub_id: str) -> SubscriptionRecord | None:
        return self._subscriptions.get(sub_id)

    def list_subscriptions(self, status: str = "") -> list[dict]:
        subs = list(self._subscriptions.values())
        if status:
            subs = [s for s in subs if s.status == status]
        return [s.to_dict() for s in subs]

    @property
    def active_subscriptions(self) -> int:
        return sum(1 for s in self._subscriptions.values() if s.is_active)

    # ── Persistence ──

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "events": [e.to_dict() for e in self._events[-200:]],
                "customers": {k: v.to_dict() for k, v in self._customers.items()},
                "subscriptions": {k: v.to_dict() for k, v in self._subscriptions.items()},
            }
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning(f"Finance memory save failed: {e}")

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            json.loads(self._path.read_text())
        except Exception as _exc:
            log.warning("swallowed_exception", action="finance_memory_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
