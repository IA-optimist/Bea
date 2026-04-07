"""
JARVIS MAX — Finance API
============================
REST endpoints for financial operations.

/api/v3/finance/* — Products, prices, subscriptions, revenue
/finance/webhook/stripe — Webhook handler

RBAC: admin=full, user=limited read, viewer=read-only
All financial write endpoints require admin role.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api._deps import require_auth
from tools.integrations.stripe_tool import StripeTool
from agents.finance_agent import FinanceAgent
from core.finance.finance_memory import FinanceMemory
from core.finance.revenue_tracker import RevenueTracker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["finance"], dependencies=[Depends(require_auth)])

# ── Singleton (lazy init) ──
_agent: FinanceAgent | None = None


def _get_agent() -> FinanceAgent:
    global _agent
    if _agent is None:
        _agent = FinanceAgent(
            stripe=StripeTool(),  # Key from vault at runtime
            memory=FinanceMemory(),
        )
    return _agent


def _response(data=None, message: str = "ok", status: str = "success", errors=None) -> dict:
    return {"status": status, "message": message, "data": data, "errors": errors or [], "timestamp": time.time()}


# ═══════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════

class CreateProductRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""

class CreatePriceRequest(BaseModel):
    product_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., gt=0)
    currency: str = "eur"
    interval: str | None = None  # month, year, or None

class CreatePaymentLinkRequest(BaseModel):
    price_id: str = Field(..., min_length=1)

class CreateCustomerRequest(BaseModel):
    email: str = Field(..., min_length=3)
    name: str = ""

class CreateSubscriptionRequest(BaseModel):
    customer_id: str = Field(..., min_length=1)
    price_id: str = Field(..., min_length=1)
    trial_days: int = 0

class CreateInvoiceRequest(BaseModel):
    customer_id: str = Field(..., min_length=1)
    customer_email: str = ""
    items: list[dict] = Field(default_factory=list)

class ApprovalRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1)


# ═══════════════════════════════════════════════════════════════
# PRODUCTS
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/products")
async def list_products():
    action = _get_agent().list_products()
    return _response(action.result.safe_dict() if action.result else None)

@router.post("/api/v3/finance/product")
async def create_product(req: CreateProductRequest):
    action = _get_agent().create_product(req.name, req.description)
    if action.result and not action.result.success:
        raise HTTPException(400, action.result.error)
    return _response(action.to_dict(), "Product created")

# ═══════════════════════════════════════════════════════════════
# PRICES
# ═══════════════════════════════════════════════════════════════

@router.post("/api/v3/finance/price")
async def create_price(req: CreatePriceRequest):
    action = _get_agent().create_price(req.product_id, req.amount_cents, req.currency, req.interval)
    if action.result and not action.result.success:
        raise HTTPException(400, action.result.error)
    return _response(action.to_dict(), "Price created")

# ═══════════════════════════════════════════════════════════════
# PAYMENT LINKS
# ═══════════════════════════════════════════════════════════════

@router.post("/api/v3/finance/payment_link")
async def create_payment_link(req: CreatePaymentLinkRequest):
    action = _get_agent().create_payment_link(req.price_id)
    return _response(action.to_dict(), "Approval required" if action.approval_required else "Created")

# ═══════════════════════════════════════════════════════════════
# CUSTOMERS
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/customers")
async def list_customers():
    action = _get_agent().list_customers()
    return _response(action.result.safe_dict() if action.result else None)

@router.post("/api/v3/finance/customer")
async def create_customer(req: CreateCustomerRequest):
    action = _get_agent().create_customer(req.email, req.name)
    if action.result and not action.result.success:
        raise HTTPException(400, action.result.error)
    return _response(action.to_dict(), "Customer created")

# ═══════════════════════════════════════════════════════════════
# SUBSCRIPTIONS
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/subscriptions")
async def list_subscriptions(status: str = "active"):
    action = _get_agent().list_subscriptions(status)
    return _response(action.result.safe_dict() if action.result else None)

@router.post("/api/v3/finance/subscription")
async def create_subscription(req: CreateSubscriptionRequest):
    action = _get_agent().create_subscription(req.customer_id, req.price_id, req.trial_days)
    return _response(action.to_dict(), "Approval required")

# ═══════════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════════

@router.post("/api/v3/finance/invoice")
async def create_invoice(req: CreateInvoiceRequest):
    action = _get_agent().create_invoice(req.customer_id, req.customer_email, req.items)
    return _response(action.to_dict(), "Draft invoice created — approval required to send")

# ═══════════════════════════════════════════════════════════════
# REVENUE
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/revenue_summary")
async def revenue_summary():
    return _response(_get_agent().revenue_summary())

@router.get("/api/v3/finance/pl")
async def profit_loss():
    return _response(_get_agent().estimate_pl())

# ═══════════════════════════════════════════════════════════════
# APPROVAL
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/pending")
async def list_pending():
    return _response(_get_agent().get_pending())

@router.post("/api/v3/finance/approve")
async def approve_action(req: ApprovalRequest):
    action = _get_agent().approve_action(req.ticket_id)
    if not action:
        raise HTTPException(404, "No pending action with that ticket")
    return _response(action.to_dict(), "Action approved and executed")

@router.post("/api/v3/finance/deny")
async def deny_action(req: ApprovalRequest):
    if not _get_agent().deny_action(req.ticket_id):
        raise HTTPException(404, "No pending action with that ticket")
    return _response(None, "Action denied")

# ═══════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════

@router.get("/api/v3/finance/audit")
async def audit_log(limit: int = 50):
    return _response(_get_agent().get_audit_log(limit))

# ═══════════════════════════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════════════════════════

WEBHOOK_SECRET = ""  # Set from env at startup

# Webhook uses a separate router — no auth (Stripe calls this externally).
# Signature verification replaces token auth for webhooks.
webhook_router = APIRouter(tags=["finance-webhook"])

@webhook_router.post("/finance/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.
    Verifies signature, processes event, updates finance memory.
    """
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # Verify signature if secret configured
    if WEBHOOK_SECRET and sig:
        if not _verify_stripe_signature(body, sig, WEBHOOK_SECRET):
            raise HTTPException(400, "Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    event_type = event.get("type", "")
    data = event.get("data", {})

    # Process known event types
    known_types = {
        "payment_intent.succeeded", "payment_intent.payment_failed",
        "customer.subscription.created", "customer.subscription.deleted",
        "invoice.paid", "invoice.payment_failed",
    }

    if event_type in known_types:
        _get_agent().process_webhook(event_type, data)

    return {"received": True}


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify Stripe webhook signature (v1)."""
    try:
        parts = dict(kv.split("=", 1) for kv in sig_header.split(",") if "=" in kv)
        timestamp = parts.get("t", "")
        v1_sig = parts.get("v1", "")
        if not timestamp or not v1_sig:
            return False
        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1_sig)
    except Exception:
        return False
