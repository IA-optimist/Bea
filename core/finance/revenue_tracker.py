"""
JARVIS MAX — Revenue Tracker
================================
Computes MRR, ARR, growth, customer value, and conversion metrics
from FinanceMemory data.

No card data. No secrets. Pure math on safe integers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from core.finance.finance_memory import FinanceMemory


@dataclass
class RevenueSnapshot:
    """Point-in-time revenue metrics."""
    mrr_cents: int = 0              # Monthly recurring revenue
    arr_cents: int = 0              # Annual recurring revenue
    active_subscriptions: int = 0
    total_customers: int = 0
    avg_customer_value_cents: int = 0
    total_revenue_cents: int = 0
    failed_payments: int = 0
    refund_total_cents: int = 0
    payment_success_rate: float = 0.0
    timestamp: float = 0

    @property
    def mrr(self) -> float:
        return self.mrr_cents / 100

    @property
    def arr(self) -> float:
        return self.arr_cents / 100

    def to_dict(self) -> dict:
        return {
            "mrr": round(self.mrr, 2),
            "arr": round(self.arr, 2),
            "mrr_cents": self.mrr_cents,
            "arr_cents": self.arr_cents,
            "active_subscriptions": self.active_subscriptions,
            "total_customers": self.total_customers,
            "avg_customer_value": round(self.avg_customer_value_cents / 100, 2) if self.avg_customer_value_cents else 0,
            "total_revenue": round(self.total_revenue_cents / 100, 2),
            "failed_payments": self.failed_payments,
            "refunds": round(self.refund_total_cents / 100, 2),
            "payment_success_rate": round(self.payment_success_rate, 3),
        }


class RevenueTracker:
    """
    Computes revenue metrics from FinanceMemory.
    
    All amounts in cents internally, converted to decimal for display.
    """

    def __init__(self, memory: FinanceMemory):
        self._memory = memory

    def snapshot(self) -> RevenueSnapshot:
        """Compute current revenue snapshot."""
        # MRR from active subscriptions
        subs = self._memory.list_subscriptions()
        active_subs = [s for s in subs if s.get("status") in ("active", "trialing")]
        mrr = sum(s.get("mrr_cents", 0) for s in active_subs)

        # Total revenue from payment events
        payments = self._memory.get_events("payment_succeeded", limit=1000)
        total_rev = sum(e.get("amount", 0) for e in payments)

        # Failed payments
        failed = self._memory.get_events("payment_failed", limit=1000)
        failed_count = len(failed)

        # Refunds
        refunds = self._memory.get_events("refund", limit=1000)
        refund_total = sum(e.get("amount", 0) for e in refunds)

        # Success rate
        total_attempts = len(payments) + failed_count
        success_rate = len(payments) / max(total_attempts, 1)

        # Customer metrics
        customers = self._memory.list_customers()
        total_cust = len(customers)
        avg_value = total_rev // max(total_cust, 1)

        return RevenueSnapshot(
            mrr_cents=mrr,
            arr_cents=mrr * 12,
            active_subscriptions=len(active_subs),
            total_customers=total_cust,
            avg_customer_value_cents=avg_value,
            total_revenue_cents=total_rev,
            failed_payments=failed_count,
            refund_total_cents=refund_total,
            payment_success_rate=success_rate,
            timestamp=time.time(),
        )

    def monthly_revenue(self, months: int = 6) -> list[dict]:
        """Get revenue by month (from events)."""
        from collections import defaultdict

        by_month: dict[str, int] = defaultdict(int)
        events = self._memory.get_events("payment_succeeded", limit=2000)

        for e in events:
            ts = e.get("timestamp", 0)
            if ts:
                t = time.gmtime(ts)
                key = f"{t.tm_year}-{t.tm_mon:02d}"
                by_month[key] += e.get("amount", 0)

        # Sort and limit
        sorted_months = sorted(by_month.items(), reverse=True)[:months]
        return [{"month": m, "revenue_cents": v, "revenue": round(v / 100, 2)} for m, v in sorted_months]

    def growth_rate(self) -> float:
        """Compute month-over-month growth rate."""
        monthly = self.monthly_revenue(3)
        if len(monthly) < 2:
            return 0.0
        current = monthly[0]["revenue_cents"]
        previous = monthly[1]["revenue_cents"]
        if previous == 0:
            return 0.0
        return round((current - previous) / previous * 100, 1)
