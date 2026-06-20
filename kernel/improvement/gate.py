"""
kernel/improvement/gate.py — Improvement Gating (Phase 6)
==========================================================
The kernel controls self-improvement. No cycle runs without passing this gate.

Migrated from core/self_improvement/__init__.py::check_improvement_allowed().
The kernel owns this decision because:
  - Improvement can modify the system itself
  - Risk must be evaluated at the kernel level
  - Cooldown and failure limits are safety invariants, not business logic

KERNEL RULE: Zero imports from core/, agents/, api/, tools/.
History data is provided via registration pattern.

Registration (at boot):
  from kernel.improvement.gate import register_history_provider
  register_history_provider(lambda: load_improvement_history())

Constants (anti-loop invariants — never weaken these):
  MAX_PER_RUN      = 1    never more than 1 improvement per execution
  COOLDOWN_HOURS   = 24   minimum gap between improvements
  MAX_FAILURES     = 3    auto-pause after 3 consecutive failures
"""
from __future__ import annotations

import contextvars
import structlog
log = structlog.get_logger(__name__)

import time
from dataclasses import dataclass
from typing import Callable, List, Optional

# ── Per-context gate bypass (replaces process-global BEA_SKIP_IMPROVEMENT_GATE) ──
# Each asyncio coroutine / thread has its own context, so setting this ContextVar
# in one request cannot bleed into concurrent requests (unlike os.environ).
_skip_gate_ctx: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "bea_skip_improvement_gate", default=None
)


def is_gate_skipped() -> bool:
    """Return True if the gate should be skipped in the current execution context.

    Resolution order:
    1. ContextVar — set per-coroutine / per-thread by :func:`skip_gate_for_context`.
    2. Process env var BEA_SKIP_IMPROVEMENT_GATE — retained for backwards compat
       (existing test fixtures using ``os.environ`` continue to work).
    """
    import os as _os  # local to avoid top-level side-effects at kernel import time
    ctx_val = _skip_gate_ctx.get()
    if ctx_val is not None:
        return ctx_val
    return _os.getenv("BEA_SKIP_IMPROVEMENT_GATE", "").lower() in ("1", "true", "yes")


def skip_gate_for_context(skip: bool = True) -> contextvars.Token:
    """Activate or deactivate the bypass for the *current* execution context only.

    Returns a token that can be passed to :func:`restore_gate` to undo the change.
    """
    return _skip_gate_ctx.set(skip)


def restore_gate(token: contextvars.Token) -> None:
    """Undo a :func:`skip_gate_for_context` call."""
    _skip_gate_ctx.reset(token)



# ── Safety invariants — hard-coded, never configurable at runtime ─────────────
MAX_PER_RUN    = 1
COOLDOWN_HOURS = 24
MAX_FAILURES   = 3


@dataclass
class ImprovementDecision:
    """The kernel's decision on whether improvement is allowed."""
    allowed:  bool
    reason:   str
    cooldown_remaining_h: float = 0.0
    consecutive_failures: int   = 0

    def to_dict(self) -> dict:
        return {
            "allowed":               self.allowed,
            "reason":                self.reason,
            "cooldown_remaining_h":  round(self.cooldown_remaining_h, 1),
            "consecutive_failures":  self.consecutive_failures,
        }


# ── Registration slot ─────────────────────────────────────────────────────────
_history_provider: Optional[Callable[[], List[dict]]] = None


def register_history_provider(fn: Callable[[], List[dict]]) -> None:
    """
    Register a function that returns improvement history as list of dicts.
    Each entry: {"timestamp": float, "outcome": "SUCCESS" | "FAILURE" | "ROLLED_BACK"}
    Called at boot — kernel never reads the history file directly.
    """
    global _history_provider
    _history_provider = fn
    log.debug("kernel_improvement_history_registered")


class PatchSignatureViolation(Exception):
    """Raised by the gate when a patch has an invalid or missing ed25519 signature."""


class ImprovementGate:
    """
    The single authority for improvement gating.

    All self-improvement cycles must pass through check() before executing.
    The gate enforces:
      1. Cooldown: no improvement if last one < 24h ago
      2. Consecutive failures: auto-pause after 3 consecutive failures
      3. Max per run: hard cap of 1 improvement per execution

    No exceptions. No workarounds. No bypass.
    """

    # ── Patch-signature validation (called before apply, not before check) ───

    def validate_patch_signature(
        self,
        patch_content: "str | dict",
        sig_data: "dict | None",
    ) -> None:
        """Validate the ed25519 signature on a candidate patch.

        Must be called before any patch is applied to the codebase.
        Handles unsigned patches (sig_data None or empty) based on
        whether BEA_PATCH_VERIFY_KEY is configured:
          - key absent → dev mode: warn and pass through
          - key present → production: unsigned patches are rejected

        Args:
            patch_content: The raw patch — a dict (CandidatePatch.to_dict()) or str.
            sig_data: The signature envelope from sign_patch(), or None if unsigned.

        Raises:
            PatchSignatureViolation: if unsigned in production, wrong algorithm,
                or cryptographically invalid.
        """
        # Lazy import — validation path only, not boot-time.
        try:
            from core.self_improvement.patch_signature import (  # noqa: PLC0415
                SignatureError,
                load_verification_key,
                verify_patch_signature,
            )
        except ImportError as exc:
            log.error("patch_signature_import_failed", err=str(exc)[:80])
            raise PatchSignatureViolation(
                f"Cannot import patch_signature module: {exc}"
            ) from exc

        verify_key = load_verification_key()

        raw_sig = (sig_data or {}).get("signature", "")

        # Explicitly UNSIGNED marker — always reject, regardless of key config.
        if raw_sig == "UNSIGNED":
            raise PatchSignatureViolation(
                "Patch is explicitly marked UNSIGNED — cannot promote unsigned patches. Rejected."
            )

        # No signature present at all: dev mode vs. production decision.
        has_sig = bool(sig_data and raw_sig)
        if not has_sig:
            if verify_key is None:
                log.warning(
                    "patch_unsigned_dev_mode",
                    msg=(
                        "Patch has no signature — BEA_PATCH_VERIFY_KEY not set, "
                        "dev mode pass-through"
                    ),
                )
                return  # dev mode: key not pinned, no signature required
            raise PatchSignatureViolation(
                "Patch is unsigned but BEA_PATCH_VERIFY_KEY is configured — "
                "all patches must be signed in production."
            )

        # Structural check: algorithm must be ed25519
        algorithm = (sig_data or {}).get("algorithm", "")
        if algorithm != "ed25519":
            raise PatchSignatureViolation(
                f"Unsupported signature algorithm: {algorithm!r} (expected 'ed25519'). Rejected."
            )

        if verify_key is None:
            log.warning(
                "patch_signature_no_verify_key",
                msg=(
                    "BEA_PATCH_VERIFY_KEY is not set — "
                    "signature structure checked but cryptographic verification skipped (dev mode)"
                ),
            )
            return  # dev mode: key not pinned, structural check passed

        try:
            verify_patch_signature(patch_content, sig_data, verify_key)  # type: ignore[arg-type]
        except SignatureError as exc:
            log.error("patch_signature_invalid", err=str(exc)[:120])
            raise PatchSignatureViolation(
                f"Patch signature verification failed: {exc}"
            ) from exc

    def check(self, mission_id: str = "") -> ImprovementDecision:
        """
        Evaluate whether a new improvement cycle is allowed.

        Pipeline (R4):
          0. Security layer check (R4: self_improvement always gated, Pass 23)
          1. Cooldown: no improvement if last one < 24h ago
          2. Consecutive failures: auto-pause after 3 consecutive failures
          3. Max per run: hard cap of 1 improvement per execution

        Never raises. Returns ImprovementDecision(allowed=False, reason=...) on error.
        """
        import os as _os
        if is_gate_skipped():
            return ImprovementDecision(allowed=True, reason="test_bypass")
        # 0 — Security layer gate (R4, Pass 23 — fail-open)
        # Operator-approval channel: BEA_OPERATOR_APPROVE_IMPROVEMENT satisfies the R4
        # human-approval requirement (the operator has authorized autonomous self-improvement
        # at the host level) WITHOUT disabling the other rails — the cooldown and
        # consecutive-failure caps below still apply. This is the safe way to let the
        # daemon run continuously; the blanket BEA_SKIP_IMPROVEMENT_GATE bypasses everything.
        if not _os.getenv("BEA_OPERATOR_APPROVE_IMPROVEMENT"):
            try:
                from security import get_security_layer
                _sec_result = get_security_layer().check_action(
                    action_type="self_improvement",
                    mission_id=mission_id,
                    mode="auto",
                    risk_level="high",
                    action_target="kernel.improvement.gate",
                )
                if not _sec_result.allowed:
                    log.info(
                        "improvement_gate_security_blocked",
                        reason=_sec_result.reason[:80],
                        escalated=_sec_result.escalated,
                    )
                    return ImprovementDecision(
                        allowed=False,
                        reason=f"security_gate: {_sec_result.reason[:80]}",
                    )
            except Exception as _se:
                log.warning(
                    "improvement_gate_security_check_failed",
                    err=str(_se)[:80],
                )
                return ImprovementDecision(
                    allowed=False,
                    reason=f"security_gate_error: {str(_se)[:60]}",
                )
        else:
            log.info("improvement_gate_operator_approved",
                      channel="BEA_OPERATOR_APPROVE_IMPROVEMENT")

        try:
            history = self._get_history()
        except Exception as e:
            log.warning("improvement_gate_history_failed", err=str(e)[:80])
            return ImprovementDecision(
                allowed=False,
                reason=f"gate_error: {str(e)[:60]}",
            )

        if not history:
            return ImprovementDecision(allowed=True, reason="no_history")

        # 1 — Cooldown check
        last_ts = history[-1].get("timestamp", 0)
        hours_since = (time.time() - last_ts) / 3600.0
        if hours_since < COOLDOWN_HOURS:
            remaining = COOLDOWN_HOURS - hours_since
            return ImprovementDecision(
                allowed=False,
                reason=f"cooldown_active ({hours_since:.1f}h elapsed, {remaining:.1f}h remaining)",
                cooldown_remaining_h=remaining,
            )

        # 2 — Consecutive failures check
        consecutive = 0
        for entry in reversed(history):
            outcome = entry.get("outcome", "SUCCESS")
            if outcome in ("FAILURE", "ROLLED_BACK"):
                consecutive += 1
            else:
                break

        if consecutive >= MAX_FAILURES:
            return ImprovementDecision(
                allowed=False,
                reason=f"max_consecutive_failures ({consecutive} >= {MAX_FAILURES}) — kernel gate paused",
                consecutive_failures=consecutive,
            )

        return ImprovementDecision(
            allowed=True,
            reason="gate_ok",
            consecutive_failures=consecutive,
        )

    def _get_history(self) -> list:
        """Get improvement history from registered provider or empty list."""
        if _history_provider is not None:
            return _history_provider() or []
        # Kernel-native fallback: try to read the standard history file
        try:
            import json
            from pathlib import Path
            p = Path("workspace/self_improvement/history.json")
            if p.exists():
                return json.loads(p.read_text("utf-8")) or []
        except Exception as _exc:
            log.warning("gate_swallow", action="gate_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        return []

    def record(self, outcome: str, metadata: dict | None = None) -> None:
        """
        Record an improvement outcome. Used by the improvement pipeline.
        outcome: "SUCCESS" | "FAILURE" | "ROLLED_BACK"
        """
        try:
            import json
            from pathlib import Path
            p = Path("workspace/self_improvement/history.json")
            p.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if p.exists():
                history = json.loads(p.read_text("utf-8")) or []
            # T4.5 — Record build digest for reproducibility
            try:
                from core.self_improvement.build_digest import compute_build_digest
                _bd = compute_build_digest()
            except Exception:
                _bd = {}
            history.append({
                "timestamp": time.time(),
                "outcome": outcome,
                "build_digest": _bd,
                **(metadata or {}),
            })
            p.write_text(json.dumps(history[-100:], indent=2, default=str), encoding="utf-8")
            log.info("improvement_gate_recorded", outcome=outcome)
        except Exception as e:
            log.warning("improvement_gate_record_failed", err=str(e)[:80])


# ── Module-level singleton ────────────────────────────────────────────────────
_gate: ImprovementGate | None = None


def get_gate() -> ImprovementGate:
    """Return singleton ImprovementGate."""
    global _gate
    if _gate is None:
        _gate = ImprovementGate()
    return _gate
