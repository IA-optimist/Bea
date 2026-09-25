from __future__ import annotations


class VerifierError(Exception):
    """Base class for all Verifier errors."""


class VerifierDenied(VerifierError):
    """Action blocked by policy. Normal denial."""

    def __init__(self, reason: str, action_id: str = "") -> None:
        self.reason = reason
        self.action_id = action_id
        super().__init__(f"[DENIED] action_id={action_id!r}: {reason}")


class VerifierHoldRequired(VerifierError):
    """Action suspended — human validation required."""

    def __init__(self, reason: str, action_id: str = "") -> None:
        self.reason = reason
        self.action_id = action_id
        super().__init__(f"[HOLD] action_id={action_id!r}: {reason}")


class VerifierHaltTriggered(VerifierError):
    """Critical violation — action blocked + alert + halt recommended."""

    def __init__(self, reason: str, action_id: str = "") -> None:
        self.reason = reason
        self.action_id = action_id
        super().__init__(f"[HALT] action_id={action_id!r}: {reason}")


class VerifierUnavailable(VerifierError):
    """Verifier cannot evaluate — fail-closed: treat as DENY."""

    def __init__(self, reason: str = "verifier unavailable") -> None:
        super().__init__(f"[UNAVAILABLE] {reason}")
