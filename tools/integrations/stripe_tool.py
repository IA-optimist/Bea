"""
JARVIS MAX — Stripe Tool
============================
Production-safe Stripe API wrapper.

All API calls:
  - Retrieve key from vault (never hardcoded)
  - Return structured StripeResponse
  - Never expose secrets in output
  - Log safely (masked)
  - Handle errors gracefully

Supported operations:
  Products: create, list
  Prices: create
  Payment Links: create
  Customers: create, list
  Subscriptions: create, list, cancel
  Invoices: create
  Payments: retrieve status
  Balance: retrieve
  Events: retrieve
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from typing import Any
_silent_log = __import__("structlog").get_logger(__name__)

logger = logging.getLogger(__name__)

STRIPE_BASE = "https://api.stripe.com/v1"
TIMEOUT = 15


@dataclass
class StripeResponse:
    """Structured response from any Stripe operation."""
    success: bool = False
    object_type: str = ""
    stripe_id: str = ""
    created_at: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""
    human_readable: str = ""
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "object_type": self.object_type,
            "stripe_id": self.stripe_id,
            "created_at": self.created_at,
            "metadata": {k: v for k, v in self.metadata.items() if k != "secret"},
            "error": self.error[:200],
            "error_code": self.error_code,
            "summary": self.human_readable[:300],
        }

    def safe_dict(self) -> dict:
        """No raw data, no secrets."""
        d = self.to_dict()
        d.pop("raw_data", None)
        return d


class StripeTool:
    """
    Stripe API wrapper with vault integration.
    
    Usage:
        tool = StripeTool(api_key=os.environ.get("STRIPE_API_KEY", ""))  # or from vault
        resp = tool.create_product("My SaaS", "AI-powered tool")
    """

    def __init__(self, api_key: str = "", vault=None, vault_secret_id: str = "stripe_api_key"):
        self._key = api_key
        self._vault = vault
        self._vault_secret_id = vault_secret_id

    def _get_key(self) -> str:
        """Get API key: explicit > vault > empty."""
        if self._key:
            return self._key
        if self._vault:
            try:
                result = self._vault.use_secret(self._vault_secret_id, agent="finance_agent")
                if result and hasattr(result, 'inject_value'):
                    return result.inject_value
                if isinstance(result, dict):
                    return result.get("value", "")
            except Exception:
                _silent_log.debug("suppressed_exception", src='stripe_tool.py')
        return ""

    # ═══════════════════════════════════════════════════════════════
    # PRODUCTS
    # ═══════════════════════════════════════════════════════════════

    def create_product(self, name: str, description: str = "",
                        metadata: dict | None = None) -> StripeResponse:
        """Create a Stripe product."""
        params = {"name": name}
        if description:
            params["description"] = description
        if metadata:
            for k, v in metadata.items():
                params[f"metadata[{k}]"] = str(v)
        resp = self._api("POST", "/products", params)
        if resp.success:
            resp.human_readable = f"Product '{name}' created: {resp.stripe_id}"
        return resp

    def list_products(self, limit: int = 20, active: bool | None = None) -> StripeResponse:
        """List products."""
        params: dict[str, str] = {"limit": str(limit)}
        if active is not None:
            params["active"] = str(active).lower()
        resp = self._api("GET", "/products", params)
        if resp.success:
            products = resp.raw_data.get("data", [])
            resp.metadata = {"count": len(products), "products": [
                {"id": p.get("id"), "name": p.get("name"), "active": p.get("active")}
                for p in products[:20]
            ]}
            resp.human_readable = f"{len(products)} products found"
        return resp

    # ═══════════════════════════════════════════════════════════════
    # PRICES
    # ═══════════════════════════════════════════════════════════════

    def create_price(self, product_id: str, amount: int, currency: str = "eur",
                      interval: str | None = None) -> StripeResponse:
        """
        Create a price for a product.
        amount: in cents (e.g., 1900 = €19.00)
        interval: 'month', 'year', or None for one-time
        """
        params = {
            "product": product_id,
            "unit_amount": str(amount),
            "currency": currency,
        }
        if interval:
            params["recurring[interval]"] = interval
        resp = self._api("POST", "/prices", params)
        if resp.success:
            display_amount = f"{amount/100:.2f} {currency.upper()}"
            recur = f"/{interval}" if interval else " one-time"
            resp.human_readable = f"Price {display_amount}{recur} created: {resp.stripe_id}"
        return resp

    # ═══════════════════════════════════════════════════════════════
    # PAYMENT LINKS
    # ═══════════════════════════════════════════════════════════════

    def create_payment_link(self, price_id: str, quantity: int = 1) -> StripeResponse:
        """Create a payment link for a price."""
        params = {
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": str(quantity),
        }
        resp = self._api("POST", "/payment_links", params)
        if resp.success:
            url = resp.raw_data.get("url", "")
            resp.metadata["url"] = url
            resp.human_readable = f"Payment link created: {url}"
        return resp

    # ═══════════════════════════════════════════════════════════════
    # CUSTOMERS
    # ═══════════════════════════════════════════════════════════════

    def create_customer(self, email: str, name: str = "",
                         metadata: dict | None = None) -> StripeResponse:
        """Create a customer."""
        params = {"email": email}
        if name:
            params["name"] = name
        if metadata:
            for k, v in metadata.items():
                params[f"metadata[{k}]"] = str(v)
        resp = self._api("POST", "/customers", params)
        if resp.success:
            resp.human_readable = f"Customer '{email}' created: {resp.stripe_id}"
        return resp

    def list_customers(self, limit: int = 20) -> StripeResponse:
        """List customers."""
        resp = self._api("GET", "/customers", {"limit": str(limit)})
        if resp.success:
            customers = resp.raw_data.get("data", [])
            resp.metadata = {"count": len(customers), "customers": [
                {"id": c.get("id"), "email": c.get("email"), "name": c.get("name")}
                for c in customers[:20]
            ]}
        return resp

    # ═══════════════════════════════════════════════════════════════
    # SUBSCRIPTIONS
    # ═══════════════════════════════════════════════════════════════

    def create_subscription(self, customer_id: str, price_id: str,
                             trial_days: int = 0) -> StripeResponse:
        """Create a subscription."""
        params = {
            "customer": customer_id,
            "items[0][price]": price_id,
        }
        if trial_days > 0:
            params["trial_period_days"] = str(trial_days)
        resp = self._api("POST", "/subscriptions", params)
        if resp.success:
            resp.human_readable = f"Subscription created for customer {customer_id}: {resp.stripe_id}"
        return resp

    def list_subscriptions(self, status: str = "active", limit: int = 20) -> StripeResponse:
        """List subscriptions."""
        resp = self._api("GET", "/subscriptions", {"status": status, "limit": str(limit)})
        if resp.success:
            subs = resp.raw_data.get("data", [])
            resp.metadata = {"count": len(subs), "subscriptions": [
                {"id": s.get("id"), "status": s.get("status"),
                 "customer": s.get("customer"), "current_period_end": s.get("current_period_end")}
                for s in subs[:20]
            ]}
        return resp

    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> StripeResponse:
        """Cancel a subscription."""
        if at_period_end:
            resp = self._api("POST", f"/subscriptions/{subscription_id}",
                              {"cancel_at_period_end": "true"})
        else:
            resp = self._api("DELETE", f"/subscriptions/{subscription_id}")
        if resp.success:
            resp.human_readable = f"Subscription {subscription_id} canceled"
        return resp

    # ═══════════════════════════════════════════════════════════════
    # INVOICES
    # ═══════════════════════════════════════════════════════════════

    def create_invoice(self, customer_id: str, items: list[dict] | None = None,
                        auto_advance: bool = False) -> StripeResponse:
        """
        Create an invoice.
        items: [{"price": "price_xxx", "quantity": 1}, ...]
        auto_advance=False means draft (requires approval to send).
        """
        params = {
            "customer": customer_id,
            "auto_advance": str(auto_advance).lower(),
        }
        resp = self._api("POST", "/invoices", params)
        if resp.success and items:
            # Add line items
            for item in items:
                self._api("POST", "/invoiceitems", {
                    "customer": customer_id,
                    "invoice": resp.stripe_id,
                    "price": item.get("price", ""),
                    "quantity": str(item.get("quantity", 1)),
                })
            resp.human_readable = f"Invoice created for {customer_id}: {resp.stripe_id} ({len(items)} items)"
        return resp

    # ═══════════════════════════════════════════════════════════════
    # PAYMENTS / BALANCE / EVENTS
    # ═══════════════════════════════════════════════════════════════

    def retrieve_payment_status(self, payment_intent_id: str) -> StripeResponse:
        """Get payment intent status."""
        resp = self._api("GET", f"/payment_intents/{payment_intent_id}")
        if resp.success:
            status = resp.raw_data.get("status", "unknown")
            amount = resp.raw_data.get("amount", 0)
            currency = resp.raw_data.get("currency", "")
            resp.metadata = {"status": status, "amount": amount, "currency": currency}
            resp.human_readable = f"Payment {payment_intent_id}: {status} ({amount/100:.2f} {currency.upper()})"
        return resp

    def retrieve_balance(self) -> StripeResponse:
        """Get Stripe account balance."""
        resp = self._api("GET", "/balance")
        if resp.success:
            available = resp.raw_data.get("available", [])
            pending = resp.raw_data.get("pending", [])
            resp.metadata = {"available": available, "pending": pending}
            total_available = sum(b.get("amount", 0) for b in available)
            resp.human_readable = f"Balance: {total_available/100:.2f} available"
        return resp

    def retrieve_event(self, event_id: str) -> StripeResponse:
        """Get a Stripe event."""
        return self._api("GET", f"/events/{event_id}")

    # ═══════════════════════════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════════════════════════

    def _api(self, method: str, path: str, params: dict | None = None) -> StripeResponse:
        """Make a Stripe API call."""
        key = self._get_key()
        if not key:
            return StripeResponse(error="No API key configured", error_code="no_key")

        url = STRIPE_BASE + path
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        body = None
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            body = urllib.parse.urlencode(params).encode()

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
                return StripeResponse(
                    success=True,
                    object_type=data.get("object", ""),
                    stripe_id=data.get("id", ""),
                    created_at=data.get("created", time.time()),
                    raw_data=data,
                )

        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode()
                err_data = json.loads(body_text)
                err = err_data.get("error", {})
                return StripeResponse(
                    error=err.get("message", f"HTTP {e.code}"),
                    error_code=err.get("code", f"http_{e.code}"),
                )
            except Exception:
                return StripeResponse(error=f"HTTP {e.code}: {body_text[:100]}", error_code=f"http_{e.code}")

        except (urllib.error.URLError, TimeoutError) as e:
            return StripeResponse(error=f"Connection failed: {str(e)[:100]}", error_code="connection_error")

        except Exception as e:
            return StripeResponse(error=str(e)[:200], error_code="unknown")

    @staticmethod
    def supported_operations() -> list[str]:
        return [
            "create_product", "list_products", "create_price",
            "create_payment_link", "create_customer", "list_customers",
            "create_subscription", "list_subscriptions", "cancel_subscription",
            "create_invoice", "retrieve_payment_status", "retrieve_balance",
        ]
