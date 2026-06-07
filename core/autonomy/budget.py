"""
core/autonomy/budget.py — Budget tracker for autonomy.

Stops a runaway daemon : per-mission and global daily budgets on tokens,
USD, wall-clock time, and consecutive failures. Once exhausted, the
mission/global budget raises `BudgetExceeded` so the caller stops or
escalates.

Three levels of budget :

1. **Mission budget** — applies to a single mission run. Resets when a
   new mission starts. Typical limits :
     - max 100k LLM tokens
     - max $1 USD
     - max 30 minutes wall time
     - max 3 consecutive sub-step failures
2. **Daily budget** — process-wide rolling window. Typical limits :
     - max 5M tokens / day
     - max $50 USD / day
3. **Operator overrides** — read from env vars at startup so VPS1
   admins can clamp without code change :
     `BEA_AUTONOMY_DAILY_USD_MAX=20`, etc.

Usage :
    bt = get_budget_tracker()
    bt.start_mission("m-001", limits=Budget(max_tokens=50_000, max_usd=0.5))
    try:
        bt.charge("m-001", tokens=1200, usd=0.012)  # raises if exceeded
    except BudgetExceeded as exc:
        log.warning("mission_halted_by_budget", err=str(exc))
        return
    bt.end_mission("m-001")

Persistence : in-memory only. Survives process restart only via the
`/api/v3/observability/budget` snapshot endpoint (caller's job to
persist if desired).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import structlog

log = structlog.get_logger(__name__)


class BudgetExceeded(Exception):
    """Raised when a charge would exceed an active budget."""

    def __init__(self, scope: str, dimension: str, current: float, limit: float):
        self.scope = scope
        self.dimension = dimension
        self.current = current
        self.limit = limit
        super().__init__(
            f"{scope} budget exceeded on {dimension} : {current:.2f} > {limit:.2f}"
        )


@dataclass
class Budget:
    """Concrete limits for a mission or daily window."""
    max_tokens: int = 0           # 0 = no limit
    max_usd: float = 0.0          # 0 = no limit
    max_seconds: float = 0.0      # 0 = no limit
    max_consecutive_failures: int = 0  # 0 = no limit


@dataclass
class _UsageCounter:
    tokens: int = 0
    usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    consecutive_failures: int = 0

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.started_at


# ── Tracker ──────────────────────────────────────────────────
class BudgetTracker:
    """Process-wide budget tracker. Thread-safe."""

    def __init__(self, daily_budget: Optional[Budget] = None):
        # Read operator overrides
        env_usd = float(os.getenv("BEA_AUTONOMY_DAILY_USD_MAX", "50"))
        env_tok = int(os.getenv("BEA_AUTONOMY_DAILY_TOKENS_MAX", "5000000"))
        self._daily_limit = daily_budget or Budget(
            max_tokens=env_tok,
            max_usd=env_usd,
            max_seconds=0,
            max_consecutive_failures=0,
        )
        self._daily_usage = _UsageCounter()
        self._daily_window_start = time.time()
        self._daily_window_s = 24 * 3600

        self._mission_limits: Dict[str, Budget] = {}
        self._mission_usage: Dict[str, _UsageCounter] = {}
        self._lock = threading.RLock()

    # ── Mission lifecycle ─────────────────────────────────────
    def start_mission(self, mission_id: str, limits: Optional[Budget] = None) -> None:
        with self._lock:
            self._mission_limits[mission_id] = limits or Budget(
                max_tokens=100_000, max_usd=1.0, max_seconds=1800, max_consecutive_failures=3
            )
            self._mission_usage[mission_id] = _UsageCounter()
        log.debug("budget.mission_started", mission_id=mission_id)

    def end_mission(self, mission_id: str) -> Optional[_UsageCounter]:
        with self._lock:
            self._mission_limits.pop(mission_id, None)
            return self._mission_usage.pop(mission_id, None)

    # ── Charges ───────────────────────────────────────────────
    def charge(
        self,
        mission_id: Optional[str] = None,
        tokens: int = 0,
        usd: float = 0.0,
    ) -> None:
        """Add token/USD usage. Raises BudgetExceeded if any limit is breached.

        Mission limits are checked first ; daily second. Both counters
        are incremented together — even on a budget breach so the
        running counter is consistent.
        """
        self._roll_daily_window_if_needed()

        with self._lock:
            # Daily : always checked
            self._daily_usage.tokens += tokens
            self._daily_usage.usd += usd
            self._check_limit("daily", "tokens", self._daily_usage.tokens, self._daily_limit.max_tokens)
            self._check_limit("daily", "usd", self._daily_usage.usd, self._daily_limit.max_usd)

            # Mission : only if active
            if mission_id and mission_id in self._mission_usage:
                u = self._mission_usage[mission_id]
                u.tokens += tokens
                u.usd += usd
                limit = self._mission_limits[mission_id]
                self._check_limit("mission", "tokens", u.tokens, limit.max_tokens)
                self._check_limit("mission", "usd", u.usd, limit.max_usd)
                if limit.max_seconds and u.elapsed_s > limit.max_seconds:
                    raise BudgetExceeded("mission", "seconds", u.elapsed_s, limit.max_seconds)

    def record_failure(self, mission_id: str) -> None:
        """Increment consecutive-failure counter. Raises if over the cap."""
        with self._lock:
            u = self._mission_usage.get(mission_id)
            if u is None:
                return
            u.consecutive_failures += 1
            limit = self._mission_limits.get(mission_id)
            if limit and limit.max_consecutive_failures:
                if u.consecutive_failures > limit.max_consecutive_failures:
                    raise BudgetExceeded(
                        "mission",
                        "consecutive_failures",
                        u.consecutive_failures,
                        limit.max_consecutive_failures,
                    )

    def record_success(self, mission_id: str) -> None:
        """Reset consecutive-failure counter on a successful step."""
        with self._lock:
            u = self._mission_usage.get(mission_id)
            if u is not None:
                u.consecutive_failures = 0

    # ── Snapshots ─────────────────────────────────────────────
    def snapshot(self) -> Dict[str, dict]:
        with self._lock:
            return {
                "daily": {
                    "tokens": self._daily_usage.tokens,
                    "usd": round(self._daily_usage.usd, 4),
                    "elapsed_s": round(time.time() - self._daily_window_start, 1),
                    "limits": {
                        "max_tokens": self._daily_limit.max_tokens,
                        "max_usd": self._daily_limit.max_usd,
                    },
                },
                "missions": {
                    mid: {
                        "tokens": u.tokens,
                        "usd": round(u.usd, 4),
                        "elapsed_s": round(u.elapsed_s, 1),
                        "consecutive_failures": u.consecutive_failures,
                    }
                    for mid, u in self._mission_usage.items()
                },
            }

    # ── Internals ─────────────────────────────────────────────
    def _check_limit(self, scope: str, dim: str, current: float, limit: float) -> None:
        if limit and current > limit:
            raise BudgetExceeded(scope, dim, current, limit)

    def _roll_daily_window_if_needed(self) -> None:
        now = time.time()
        with self._lock:
            if now - self._daily_window_start > self._daily_window_s:
                log.info(
                    "budget.daily_window_rolled",
                    prev_tokens=self._daily_usage.tokens,
                    prev_usd=round(self._daily_usage.usd, 4),
                )
                self._daily_usage = _UsageCounter()
                self._daily_window_start = now


# ── Singleton ────────────────────────────────────────────────
_TRACKER: Optional[BudgetTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_budget_tracker() -> BudgetTracker:
    global _TRACKER
    if _TRACKER is None:
        with _TRACKER_LOCK:
            if _TRACKER is None:
                _TRACKER = BudgetTracker()
    return _TRACKER


def reset_budget_tracker() -> None:
    """Test fixture hook."""
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = None
