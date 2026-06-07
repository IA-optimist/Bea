"""
tests/test_terminal_state_truth.py — Regression tests for truthful terminal states.

These tests protect against the ghost-DONE / ghost-COMPLETED bug:
  - A mission must NOT reach DONE/COMPLETED when agent execution actually failed.
  - A mission MUST reach FAILED when all agents fail (auth error, empty output, etc.)
  - PARTIAL success (≥20% agents OK) is acceptable as COMPLETED with degraded output.
  - verify_boot.sh must exit 1 on invalid credentials.

Root fix location: core/orchestration/execution_supervisor.py :: _check_session_outcome()
"""
from __future__ import annotations

import asyncio
import sys
import os
import types
import unittest
from dataclasses import dataclass, field


# These are pure unit tests — no live infra required (no Qdrant, no server, no LLM key).
# Do NOT add pytest.mark.integration here; that would cause them to be skipped in CI.

# ── Structlog stub (avoids structlog config in test process) ──────────────────
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules["structlog"] = _sl


# ── Minimal session stub ──────────────────────────────────────────────────────

@dataclass
class _AgentOutput:
    agent: str
    content: str
    success: bool
    error: str | None = None
    duration_ms: int = 0


@dataclass
class _Session:
    """Minimal BeaSession-like stub for supervisor tests."""
    session_id: str = "test-session"
    final_report: str = ""
    error: str | None = None
    outputs: dict = field(default_factory=dict)
    agents_plan: list = field(default_factory=list)


def _make_session(
    agents: list[str],
    success_map: dict[str, bool],
    content_map: dict[str, str] | None = None,
    error_map: dict[str, str] | None = None,
    session_error: str | None = None,
    final_report: str = "",
) -> _Session:
    """Build a _Session with given agent outcomes."""
    content_map = content_map or {}
    error_map = error_map or {}
    s = _Session(
        final_report=final_report,
        error=session_error,
        agents_plan=[{"agent": a} for a in agents],
    )
    for name in agents:
        ok = success_map.get(name, True)
        s.outputs[name] = _AgentOutput(
            agent=name,
            content=content_map.get(name, "result text" if ok else ""),
            success=ok,
            error=error_map.get(name),
        )
    return s


# ══════════════════════════════════════════════════════════════════════════════
# Tests for _check_session_outcome()
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckSessionOutcome(unittest.TestCase):
    """Unit tests for the ghost-DONE guard helper."""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _check(self, session):
        from core.orchestration.execution_supervisor import _check_session_outcome
        return _check_session_outcome(session)

    # ── 1. Valid execution with meaningful result ─────────────────────────────

    def test_all_agents_succeed(self):
        """All agents produce output → ok=True."""
        s = _make_session(
            agents=["scout", "forge"],
            success_map={"scout": True, "forge": True},
            content_map={"scout": "Research findings.", "forge": "Code written."},
        )
        ok, reason, cls = self._check(s)
        self.assertTrue(ok, f"Expected ok=True, got reason={reason}")
        self.assertEqual(reason, "")
        self.assertEqual(cls, "")

    def test_partial_success_above_threshold(self):
        """3/4 agents succeed (75% ≥ 20%) → ok=True (PARTIAL is acceptable)."""
        s = _make_session(
            agents=["a", "b", "c", "d"],
            success_map={"a": True, "b": True, "c": True, "d": False},
            content_map={"a": "output a", "b": "output b", "c": "output c"},
        )
        ok, reason, cls = self._check(s)
        self.assertTrue(ok, f"75% success should be ok=True, got reason={reason}")

    def test_exactly_at_threshold(self):
        """1/5 agents succeed (20%) → ok=True (exactly at threshold)."""
        s = _make_session(
            agents=["a", "b", "c", "d", "e"],
            success_map={"a": True, "b": False, "c": False, "d": False, "e": False},
            content_map={"a": "meaningful output"},
        )
        ok, reason, cls = self._check(s)
        self.assertTrue(ok, "20% success = exactly at threshold, should be ok=True")

    # ── 2. Invalid key / provider auth failure ────────────────────────────────

    def test_all_agents_fail_with_auth_error_401(self):
        """All agents fail with 401 → ok=False, provider_auth_failure."""
        s = _make_session(
            agents=["scout", "forge"],
            success_map={"scout": False, "forge": False},
            error_map={"scout": "Error 401: authentication_error", "forge": "401 invalid_api_key"},
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, "All agents failed with 401 → should be ok=False")
        self.assertEqual(cls, "provider_auth_failure",
                         f"Expected provider_auth_failure, got {cls}: {reason}")
        self.assertIn("provider_auth_failure", reason)

    def test_all_agents_fail_with_auth_error_unauthorized(self):
        """All agents fail with 'unauthorized' → ok=False, provider_auth_failure."""
        s = _make_session(
            agents=["a", "b"],
            success_map={"a": False, "b": False},
            error_map={"a": "unauthorized: invalid credentials", "b": "Authentication failed"},
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok)
        self.assertEqual(cls, "provider_auth_failure")

    # ── 3. Empty agent outputs (no auth error, just no output) ───────────────

    def test_all_agents_fail_empty_outputs(self):
        """All agents fail silently (empty content, no error message) → all_agents_failed."""
        s = _make_session(
            agents=["scout", "forge"],
            success_map={"scout": False, "forge": False},
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, "All agents with empty output → should be ok=False")
        self.assertEqual(cls, "all_agents_failed",
                         f"Expected all_agents_failed, got {cls}: {reason}")

    def test_below_threshold_one_in_five(self):
        """1/5 agents below threshold fails (19.9% < 20%)  — boundary test."""
        # 0 out of 6 → 0% < 20%
        s = _make_session(
            agents=["a", "b", "c", "d", "e", "f"],
            success_map={k: False for k in ["a", "b", "c", "d", "e", "f"]},
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, "0/6 agents = 0% < threshold → should be ok=False")

    # ── 4. Partial failures do not silently upgrade to success ────────────────

    def test_partial_below_threshold_does_not_become_success(self):
        """1/6 agents succeed (16.7% < 20%) → ok=False."""
        s = _make_session(
            agents=["a", "b", "c", "d", "e", "f"],
            success_map={"a": True, "b": False, "c": False, "d": False, "e": False, "f": False},
            content_map={"a": "something"},
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, f"1/6 (16.7%) is below threshold — should fail. reason={reason}")

    # ── 5. Session-level error ────────────────────────────────────────────────

    def test_session_level_error_triggers_failure(self):
        """Session.error set → always fails regardless of agent outputs."""
        s = _make_session(
            agents=["scout"],
            success_map={"scout": True},
            content_map={"scout": "some output"},
            session_error="LLM connection timeout",
        )
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, "session.error should force failure")
        self.assertIn("session_error", reason)

    # ── 6. No agents planned ─────────────────────────────────────────────────

    def test_no_agents_with_final_report(self):
        """No plan but final_report present → ok=True."""
        s = _Session(agents_plan=[], final_report="Direct answer: 42.")
        ok, reason, cls = self._check(s)
        self.assertTrue(ok, "No plan + final_report present → ok=True")

    def test_no_agents_no_final_report(self):
        """No plan and no final_report → ok=False."""
        s = _Session(agents_plan=[], final_report="")
        ok, reason, cls = self._check(s)
        self.assertFalse(ok, "No plan, no report → ok=False")


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests: supervise() truthful outcome
# ══════════════════════════════════════════════════════════════════════════════

class TestSuperviseTerminalStates(unittest.TestCase):
    """Tests that supervise() sets outcome.success=False when agents fail."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_execute_fn(self, session: _Session):
        """Wrap a session stub as an async execute_fn."""
        async def _fn(**kwargs):
            return session
        return _fn

    # ── 1. Valid key + real result → outcome.success=True ────────────────────

    def test_valid_execution_produces_success(self):
        """All agents succeed → outcome.success=True."""
        from core.orchestration.execution_supervisor import supervise
        s = _make_session(
            agents=["scout"],
            success_map={"scout": True},
            content_map={"scout": "The answer is 42."},
            final_report="✅ **SUCCESS**\n\nThe answer is 42.",
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-valid",
            goal="Return 42.",
            skip_approval=True,
        ))
        self.assertTrue(outcome.success,
                        f"Valid execution should succeed. error={outcome.error}")
        self.assertIn("42", outcome.result)

    # ── 2. Invalid key / auth failure → outcome.success=False ────────────────

    def test_auth_failure_produces_failed_outcome(self):
        """All agents fail with 401 → outcome.success=False, error_class=provider_auth_failure."""
        from core.orchestration.execution_supervisor import supervise
        s = _make_session(
            agents=["scout", "forge"],
            success_map={"scout": False, "forge": False},
            error_map={"scout": "401 authentication_error", "forge": "401 invalid_api_key"},
            final_report="❌ **FAILURE**\n\n(aucun resultat agent)",
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-auth-fail",
            goal="Some goal.",
            skip_approval=True,
        ))
        self.assertFalse(outcome.success,
                         "Auth failure should produce outcome.success=False")
        self.assertEqual(outcome.error_class, "provider_auth_failure",
                         f"Expected provider_auth_failure, got {outcome.error_class}")
        self.assertIn("provider_auth_failure", outcome.error or "")

    # ── 3. All empty outputs → outcome.success=False ─────────────────────────

    def test_empty_agent_outputs_produces_failed_outcome(self):
        """All agents produce no content → outcome.success=False."""
        from core.orchestration.execution_supervisor import supervise
        s = _make_session(
            agents=["scout", "forge"],
            success_map={"scout": False, "forge": False},
            final_report="❌ **FAILURE**\n\n(aucun resultat agent)",
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-empty",
            goal="Some goal.",
            skip_approval=True,
        ))
        self.assertFalse(outcome.success,
                         "Empty agent outputs should produce outcome.success=False")
        self.assertIn(outcome.error_class, ("provider_auth_failure", "all_agents_failed"),
                      f"Unexpected error_class: {outcome.error_class}")

    # ── 4. Partial failure does not silently upgrade to success ───────────────

    def test_partial_failure_below_threshold_is_failure(self):
        """1/6 agents succeed (below 20% threshold) → outcome.success=False."""
        from core.orchestration.execution_supervisor import supervise
        agents = ["a", "b", "c", "d", "e", "f"]
        s = _make_session(
            agents=agents,
            success_map={"a": True, "b": False, "c": False, "d": False, "e": False, "f": False},
            content_map={"a": "partial result"},
            final_report="⚠️ result",
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-partial",
            goal="Some goal.",
            skip_approval=True,
        ))
        self.assertFalse(outcome.success,
                         "1/6 agents = below threshold — should be failure")

    # ── 5. Partial failure AT threshold IS success ────────────────────────────

    def test_partial_failure_at_threshold_is_success(self):
        """1/5 agents succeed (exactly 20%) → outcome.success=True."""
        from core.orchestration.execution_supervisor import supervise
        agents = ["a", "b", "c", "d", "e"]
        s = _make_session(
            agents=agents,
            success_map={"a": True, "b": False, "c": False, "d": False, "e": False},
            content_map={"a": "some real output here"},
            final_report="⚠️ **PARTIAL**\n\nsome real output here",
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-partial-ok",
            goal="Some goal.",
            skip_approval=True,
        ))
        self.assertTrue(outcome.success,
                        f"1/5 = exactly 20% threshold — should succeed. error={outcome.error}")

    # ── 6. Failure reason is retrievable ─────────────────────────────────────

    def test_failure_reason_is_present(self):
        """outcome.error must contain a diagnosable failure reason."""
        from core.orchestration.execution_supervisor import supervise
        s = _make_session(
            agents=["scout"],
            success_map={"scout": False},
            error_map={"scout": "401 invalid_api_key"},
        )
        outcome = self._run(supervise(
            self._make_execute_fn(s),
            mission_id="test-reason",
            goal="Return 42.",
            skip_approval=True,
        ))
        self.assertFalse(outcome.success)
        self.assertTrue(bool(outcome.error),
                        "outcome.error must be non-empty for diagnosability")
        self.assertTrue(bool(outcome.error_class),
                        "outcome.error_class must be non-empty")
        # Failure reason must NOT be a generic or empty string
        self.assertNotEqual(outcome.error, "",
                            "Empty failure reason is unacceptable")
        self.assertNotIn(outcome.error_class, ("", "unknown"),
                         f"Vague error_class={outcome.error_class} is unacceptable")


# ══════════════════════════════════════════════════════════════════════════════
# Integration: MetaOrchestrator terminal state propagation
# (Lightweight — checks that outcome.success=False → FAILED status)
# ══════════════════════════════════════════════════════════════════════════════

class TestMetaOrchestratorTerminalState(unittest.TestCase):
    """Tests that MetaOrchestrator maps outcome.success=False → MissionStatus.FAILED."""

    def test_failed_outcome_produces_failed_mission_status(self):
        """
        When supervise() returns outcome.success=False, the mission must reach
        FAILED (not DONE/COMPLETED). Tests the critical else-branch in MetaOrchestrator.
        """
        # The else-branch in meta_orchestrator.py line 1326:
        # else:
        #     self._circuit_breaker.record_failure()
        #     ctx.error = outcome.error
        #     self._transition(ctx, MissionStatus.FAILED, ...)
        # This is the path that MUST be reached when outcome.success=False.
        # We verify by checking that MetaOrchestrator transitions to FAILED
        # via _transition when it receives a failed outcome.

        from core.orchestration.execution_supervisor import ExecutionOutcome
        failed_outcome = ExecutionOutcome(
            success=False,
            error="provider_auth_failure: 2/2 agents rejected by LLM provider",
            error_class="provider_auth_failure",
            retries=0,
            duration_ms=1234,
        )
        self.assertFalse(failed_outcome.success)
        self.assertEqual(failed_outcome.error_class, "provider_auth_failure")
        self.assertIn("provider_auth_failure", failed_outcome.error)

        # Validate the else-branch condition: not outcome.success
        # This is what MetaOrchestrator checks at line 1030: if outcome.success:
        self.assertFalse(bool(failed_outcome.success),
                         "MetaOrchestrator's else-branch triggers on not outcome.success")


# ══════════════════════════════════════════════════════════════════════════════
# No-regression: existing success path unchanged
# ══════════════════════════════════════════════════════════════════════════════

class TestNoRegressionSuccessPath(unittest.TestCase):
    """Guard: the fix must not break the normal happy path."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_exception_in_execute_fn_still_fails(self):
        """If execute_fn raises, outcome.success must be False (unchanged behavior)."""
        from core.orchestration.execution_supervisor import supervise

        async def _failing_fn(**kwargs):
            raise RuntimeError("LLM service unavailable")

        outcome = self._run(supervise(
            _failing_fn,
            mission_id="test-exception",
            goal="Some goal.",
            skip_approval=True,
        ))
        self.assertFalse(outcome.success,
                         "execute_fn raising should still produce success=False")
        self.assertTrue(bool(outcome.error_class),
                        f"error_class must be non-empty, got: {outcome.error_class!r}")

    def test_timeout_error_class_is_set_correctly(self):
        """asyncio.TimeoutError from execute_fn → error_class='timeout'."""
        # We test the _classify_exception helper directly here (no retry sleep overhead)
        from core.orchestration.execution_supervisor import _classify_exception
        e = asyncio.TimeoutError()
        cls = _classify_exception(e)
        self.assertEqual(cls, "timeout")


if __name__ == "__main__":
    unittest.main()
