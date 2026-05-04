"""
JARVIS MAX — Surgical Hardening Test Suite
==========================================

Regression and coverage tests for all changes made during the
surgical hardening pass (2026-03-28, pass 2).

Areas covered:
  A. MetaOrchestrator
     - outcome.actions guard (was AttributeError → silent skill discovery failure)
     - circuit breaker: opens after threshold failures
     - circuit breaker: rejects missions when open
     - circuit breaker: resets after timeout
     - circuit breaker: records success / failure correctly
     - circuit breaker: status visible in get_status()
     - outcome.decision_trace schema validation guard
  B. execution_supervisor
     - _ATTEMPT_TIMEOUT_S constant exists and is positive
     - _APPROVAL_SUBMIT_TIMEOUT_S constant exists and is positive
     - execute_fn call is wrapped in asyncio.wait_for (source audit)
     - _request_approval is async
     - ExecutionOutcome has all required fields
     - ExecutionOutcome.to_dict() is complete
  C. CapabilityDispatcher
     - _MCP_TIMEOUT_S / _NATIVE_TIMEOUT_S / _PLUGIN_TIMEOUT_S defined and positive
     - dispatch() never raises (always returns CapabilityResult)
     - MCP timeout fires and returns CapabilityResult.failure
     - native tool timeout fires correctly
  D. MemoryFacade
     - search() never raises regardless of backend state
     - search() completes within reasonable time (no blocking)
     - thread-based bus search uses daemon threads
  E. Contract Safety
     - ExecutionOutcome.decision_trace is always a list
     - ExecutionOutcome.recovery_actions is always a list
     - decision_trace entries must be dicts
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import os
import time
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ══════════════════════════════════════════════════════════════════════════════
# A. METAORCHESTRATOR — circuit breaker + schema guard
# ══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """_CircuitBreaker must protect the runtime from cascade failures."""

    def _get_cb(self, threshold=3, reset_s=1.0):
        from core.meta_orchestrator import _CircuitBreaker
        return _CircuitBreaker(failure_threshold=threshold, reset_s=reset_s)

    def test_circuit_breaker_exists(self):
        """_CircuitBreaker must be importable from meta_orchestrator."""
        from core.meta_orchestrator import _CircuitBreaker
        assert _CircuitBreaker is not None

    def test_initially_closed(self):
        cb = self._get_cb()
        assert cb.is_open is False

    def test_stays_closed_below_threshold(self):
        cb = self._get_cb(threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is False

    def test_opens_at_threshold(self):
        cb = self._get_cb(threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

    def test_success_resets_failures(self):
        cb = self._get_cb(threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()  # Only 1 failure since last success
        assert cb.is_open is False

    def test_auto_resets_after_timeout(self):
        cb = self._get_cb(threshold=1, reset_s=0.05)  # 50ms reset
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.1)  # Wait for reset
        assert cb.is_open is False

    def test_status_dict_has_required_keys(self):
        cb = self._get_cb()
        status = cb.status()
        assert "open" in status
        assert "failures" in status
        assert "open_until" in status

    def test_thread_safe_concurrent_failures(self):
        """Multiple threads recording failures must not corrupt state."""
        cb = self._get_cb(threshold=100, reset_s=60.0)
        errors = []

        def _fail():
            try:
                for _ in range(10):
                    cb.record_failure()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_fail) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread-safety errors: {errors}"
        assert cb.status()["failures"] == 100


class TestMetaOrchestratorCircuitBreakerIntegration:
    """MetaOrchestrator must initialize and use circuit breaker."""

    def test_circuit_breaker_initialized(self):
        from core.meta_orchestrator import MetaOrchestrator, _CircuitBreaker
        mo = MetaOrchestrator()
        assert hasattr(mo, "_circuit_breaker")
        assert isinstance(mo._circuit_breaker, _CircuitBreaker)

    def test_get_status_includes_circuit_breaker(self):
        from core.meta_orchestrator import MetaOrchestrator
        mo = MetaOrchestrator()
        status = mo.get_status()
        assert "circuit_breaker" in status
        assert "open" in status["circuit_breaker"]
        assert "failures" in status["circuit_breaker"]

    def test_open_circuit_rejects_mission(self):
        """When circuit breaker is open, run_mission must fast-fail immediately."""
        from core.meta_orchestrator import MetaOrchestrator
        from core.state import MissionStatus
        mo = MetaOrchestrator()
        # Force circuit open
        mo._circuit_breaker._threshold = 1
        mo._circuit_breaker.record_failure()
        assert mo._circuit_breaker.is_open

        loop = asyncio.new_event_loop()
        try:
            ctx = loop.run_until_complete(mo.run_mission("test goal"))
        finally:
            loop.close()
        assert ctx.status == MissionStatus.FAILED
        assert "circuit" in (ctx.error or "").lower()

    def test_outcome_actions_guard(self):
        """The getattr guard must prevent AttributeError on outcome.actions."""
        # Verify source contains the safe guard
        from core import meta_orchestrator as mo
        src = inspect.getsource(mo)
        assert 'getattr(outcome, "actions", [])' in src or "getattr(outcome, 'actions', [])" in src, (
            "outcome.actions guard not found in meta_orchestrator source"
        )

    def test_decision_trace_schema_guard(self):
        """decision_trace must be guarded with isinstance check before iteration."""
        from core import meta_orchestrator as mo
        src = inspect.getsource(mo.MetaOrchestrator.run_mission)
        assert "isinstance" in src, (
            "decision_trace schema validation missing from run_mission"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B. EXECUTION SUPERVISOR
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutionSupervisorTimeouts:
    """Supervisor must enforce per-attempt and approval timeouts."""

    def test_attempt_timeout_constant_defined(self):
        from core.orchestration.execution_supervisor import _ATTEMPT_TIMEOUT_S
        assert isinstance(_ATTEMPT_TIMEOUT_S, (int, float))
        assert _ATTEMPT_TIMEOUT_S > 0

    def test_approval_submit_timeout_constant_defined(self):
        from core.orchestration.execution_supervisor import _APPROVAL_SUBMIT_TIMEOUT_S
        assert isinstance(_APPROVAL_SUBMIT_TIMEOUT_S, (int, float))
        assert _APPROVAL_SUBMIT_TIMEOUT_S > 0

    def test_execute_fn_wrapped_in_wait_for(self):
        """The execute_fn call in supervise() must be wrapped in asyncio.wait_for."""
        from core.orchestration.execution_supervisor import supervise
        src = inspect.getsource(supervise)
        assert "wait_for" in src, (
            "asyncio.wait_for not found around execute_fn — per-attempt timeout missing"
        )

    def test_attempt_timeout_is_reasonable(self):
        """Attempt timeout must be reasonable: > 30s and < 1800s."""
        from core.orchestration.execution_supervisor import _ATTEMPT_TIMEOUT_S
        assert _ATTEMPT_TIMEOUT_S >= 30, "Attempt timeout too short (< 30s)"
        assert _ATTEMPT_TIMEOUT_S <= 1800, "Attempt timeout too long (> 30min)"

    def test_request_approval_is_async(self):
        """_request_approval must be an async function."""
        from core.orchestration.execution_supervisor import _request_approval
        assert asyncio.iscoroutinefunction(_request_approval)

    def test_approval_function_contains_wait_for(self):
        """_request_approval must use asyncio.wait_for for the submission."""
        from core.orchestration.execution_supervisor import _request_approval
        src = inspect.getsource(_request_approval)
        assert "wait_for" in src, (
            "asyncio.wait_for not found in _request_approval — approval submission timeout missing"
        )


class TestExecutionOutcomeContract:
    """ExecutionOutcome must satisfy its contract at all times."""

    def test_default_outcome_has_list_fields(self):
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome()
        assert isinstance(o.decision_trace, list)
        assert isinstance(o.recovery_actions, list)

    def test_decision_trace_entries_are_dicts(self):
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome()
        o.decision_trace.append({"step": "test", "value": 1})
        for d in o.decision_trace:
            assert isinstance(d, dict)

    def test_to_dict_always_succeeds(self):
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome(
            success=True,
            result="some result",
            error="",
            error_class="",
            retries=1,
            duration_ms=500,
        )
        d = o.to_dict()
        required = {"success", "result", "error", "error_class", "retries",
                    "recovery_actions", "duration_ms", "decision_trace"}
        assert required.issubset(d.keys()), f"Missing keys: {required - d.keys()}"

    def test_to_dict_truncates_result(self):
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome(result="X" * 1000)
        d = o.to_dict()
        assert len(d["result"]) <= 500

    def test_to_dict_truncates_error(self):
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome(error="E" * 500)
        d = o.to_dict()
        assert len(d["error"]) <= 200

    def test_outcome_has_no_actions_field(self):
        """ExecutionOutcome must NOT have an 'actions' field (it was a bug source).
        Callers must use getattr(outcome, 'actions', []) defensively."""
        from core.orchestration.execution_supervisor import ExecutionOutcome
        o = ExecutionOutcome()
        assert not hasattr(o, "actions"), (
            "ExecutionOutcome.actions should not exist — callers must use getattr guard"
        )

    def test_recovery_action_enum_values(self):
        from core.orchestration.execution_supervisor import RecoveryAction
        valid = {"retry", "replan", "fallback", "escalate", "abort"}
        for action in RecoveryAction:
            assert action.value in valid


class TestDecideRecovery:
    """_decide_recovery must return consistent RecoveryAction values."""

    def test_high_risk_always_escalates(self):
        from core.orchestration.execution_supervisor import _decide_recovery, RecoveryAction
        assert _decide_recovery("timeout", 0, "high") == RecoveryAction.ESCALATE
        assert _decide_recovery("connection_error", 0, "critical") == RecoveryAction.ESCALATE

    def test_permanent_error_aborts(self):
        from core.orchestration.execution_supervisor import _decide_recovery, RecoveryAction
        assert _decide_recovery("permission_denied", 0, "low") == RecoveryAction.ABORT
        assert _decide_recovery("not_found", 0, "low") == RecoveryAction.ABORT

    def test_transient_error_retries_first(self):
        from core.orchestration.execution_supervisor import _decide_recovery, RecoveryAction
        result = _decide_recovery("timeout", 0, "low")
        assert result == RecoveryAction.RETRY

    def test_transient_falls_back_after_max(self):
        from core.orchestration.execution_supervisor import _decide_recovery, RecoveryAction, _MAX_RETRIES
        result = _decide_recovery("timeout", _MAX_RETRIES, "low")
        assert result == RecoveryAction.FALLBACK


# ══════════════════════════════════════════════════════════════════════════════
# C. CAPABILITY DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

class TestCapabilityDispatcherTimeouts:
    """Dispatcher must have timeout constants and enforce them."""

    def test_mcp_timeout_defined(self):
        from executor.capability_dispatch import _MCP_TIMEOUT_S
        assert isinstance(_MCP_TIMEOUT_S, (int, float))
        assert _MCP_TIMEOUT_S > 0

    def test_native_timeout_defined(self):
        from executor.capability_dispatch import _NATIVE_TIMEOUT_S
        assert isinstance(_NATIVE_TIMEOUT_S, (int, float))
        assert _NATIVE_TIMEOUT_S > 0

    def test_plugin_timeout_defined(self):
        from executor.capability_dispatch import _PLUGIN_TIMEOUT_S
        assert isinstance(_PLUGIN_TIMEOUT_S, (int, float))
        assert _PLUGIN_TIMEOUT_S > 0

    def test_dispatch_mcp_source_has_wait_for(self):
        """_dispatch_mcp must wrap invoke_tool in asyncio.wait_for."""
        from executor.capability_dispatch import CapabilityDispatcher
        src = inspect.getsource(CapabilityDispatcher._dispatch_mcp)
        assert "wait_for" in src, (
            "asyncio.wait_for not found in _dispatch_mcp — MCP call has no timeout"
        )

    def test_dispatch_native_source_has_wait_for(self):
        """_dispatch_native must wrap handler in asyncio.wait_for."""
        from executor.capability_dispatch import CapabilityDispatcher
        src = inspect.getsource(CapabilityDispatcher._dispatch_native)
        assert "wait_for" in src, (
            "asyncio.wait_for not found in _dispatch_native — native tool has no timeout"
        )

    def test_dispatch_mcp_timeout_returns_failure_result(self):
        """When MCP times out, dispatch() must return CapabilityResult failure, not raise."""
        from executor.capability_dispatch import CapabilityDispatcher
        from executor.capability_contracts import CapabilityRequest, CapabilityType

        dispatcher = CapabilityDispatcher()

        # Attach a fake MCP adapter that hangs
        class _HangingAdapter:
            async def invoke_tool(self, *args, **kwargs):
                await asyncio.sleep(9999)  # Will be interrupted by timeout

        dispatcher.set_mcp_adapter(_HangingAdapter())
        dispatcher._MCP_TIMEOUT_S = 0.05  # Override to 50ms for test speed

        # Patch the module-level constant for this test
        import executor.capability_dispatch as cd_module
        original = cd_module._MCP_TIMEOUT_S
        cd_module._MCP_TIMEOUT_S = 0.05

        req = CapabilityRequest(
            capability_id="test_mcp_tool",
            capability_type=CapabilityType.MCP_TOOL,
            action="test",
            params={},
            context={},
        )

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(dispatcher.dispatch(req))
            # CapabilityResult uses .ok as the success field
            assert result.ok is False, "Timeout must result in failure (ok=False)"
        finally:
            loop.close()
            cd_module._MCP_TIMEOUT_S = original

    def test_dispatch_native_unregistered_returns_failure(self):
        """Dispatching to an unregistered native tool must return failure, not raise."""
        from executor.capability_dispatch import CapabilityDispatcher
        from executor.capability_contracts import CapabilityRequest, CapabilityType

        dispatcher = CapabilityDispatcher()
        req = CapabilityRequest(
            capability_id="nonexistent_tool",
            capability_type=CapabilityType.NATIVE_TOOL,
            action="run",
            params={},
            context={},
        )
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(dispatcher.dispatch(req))
        finally:
            loop.close()
        assert result.ok is False  # CapabilityResult uses .ok not .success

    def test_dispatch_never_raises(self):
        """dispatch() must never raise, regardless of input."""
        from executor.capability_dispatch import CapabilityDispatcher
        from executor.capability_contracts import CapabilityRequest

        dispatcher = CapabilityDispatcher()

        # Unknown capability type (will hit the else branch)
        req = CapabilityRequest(
            capability_id="unknown",
            capability_type="INVALID_TYPE",  # type: ignore
            action="run",
            params={},
            context={},
        )
        # Should not raise
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(dispatcher.dispatch(req))
            # Either returns failure or raises — we just verify no unhandled exception
        except Exception as e:
            pytest.fail(f"dispatch() raised unexpectedly: {e}")
        finally:
            loop.close()

    def test_dispatcher_instantiates(self):
        from executor.capability_dispatch import get_capability_dispatcher
        d = get_capability_dispatcher()
        assert d is not None

    def test_dispatcher_singleton(self):
        from executor.capability_dispatch import get_capability_dispatcher
        a = get_capability_dispatcher()
        b = get_capability_dispatcher()
        assert a is b


# ══════════════════════════════════════════════════════════════════════════════
# D. MEMORY FACADE — async bus fix
# ══════════════════════════════════════════════════════════════════════════════

class TestMemoryFacadeAsyncFix:
    """Memory search must not silently bypass vector search in async context."""

    def test_search_source_no_silent_pass(self, tmp_path):
        """The 'pass  # Can't await in sync context' bypass must be gone."""
        from core.memory_facade import MemoryFacade
        src = inspect.getsource(MemoryFacade.search)
        assert "Can't await in sync context" not in src, (
            "Silent async bypass comment still present — fix not applied"
        )

    def test_search_uses_thread_for_bus(self, tmp_path):
        """memory_bus search must use a daemon thread (not skip in async context)."""
        from core.memory_facade import MemoryFacade
        src = inspect.getsource(MemoryFacade.search)
        assert "threading.Thread" in src or "Thread" in src, (
            "Thread-based memory bus search not found"
        )

    def test_search_completes_within_deadline(self, tmp_path):
        """search() must complete within 5s even when memory bus is unavailable."""
        from core.memory_facade import MemoryFacade
        facade = MemoryFacade(workspace_dir=str(tmp_path))
        start = time.time()
        results = facade.search("test query", top_k=3)
        elapsed = time.time() - start
        assert elapsed < 5.0, f"search() took too long: {elapsed:.2f}s"
        assert isinstance(results, list)

    def test_search_from_sync_context_does_not_raise(self, tmp_path):
        """search() must never raise regardless of event loop state."""
        from core.memory_facade import MemoryFacade
        facade = MemoryFacade(workspace_dir=str(tmp_path))
        results = facade.search("authentication query")
        assert isinstance(results, list)

    def test_imports_threading(self):
        """memory_facade module must import threading (needed for bus search fix)."""
        import core.memory_facade as mf
        src = inspect.getsource(mf)
        assert "import threading" in src, "threading not imported in memory_facade"

    def test_imports_queue(self):
        """memory_facade module must import queue module (needed for bus search fix)."""
        import core.memory_facade as mf
        src = inspect.getsource(mf)
        assert "queue" in src, "queue module not imported in memory_facade"


# ══════════════════════════════════════════════════════════════════════════════
# E. EXECUTION SUPERVISOR — classify and recovery integration
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyException:
    """_classify_exception must map exceptions to correct error categories."""

    def test_timeout_name_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        assert _classify_exception(TimeoutError("timed out")) == "timeout"

    def test_permission_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        err = PermissionError("access denied")
        assert _classify_exception(err) == "permission_denied"

    def test_404_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        result = _classify_exception(RuntimeError("404 not found"))
        assert result == "not_found"

    def test_rate_limit_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        result = _classify_exception(RuntimeError("rate limit exceeded"))
        assert result == "rate_limit"

    def test_llm_error_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        result = _classify_exception(RuntimeError("openai error"))
        assert result == "llm_error"

    def test_connection_classified(self):
        from core.orchestration.execution_supervisor import _classify_exception
        result = _classify_exception(ConnectionError("network failed"))
        assert result == "connection_error"

    def test_generic_is_execution_error(self):
        from core.orchestration.execution_supervisor import _classify_exception
        result = _classify_exception(RuntimeError("something weird"))
        assert result == "execution_error"


# ══════════════════════════════════════════════════════════════════════════════
# F. CAPABILITY CONTRACTS
# ══════════════════════════════════════════════════════════════════════════════

class TestCapabilityContracts:
    """CapabilityRequest and CapabilityResult must be importable and correct."""

    def test_capability_request_importable(self):
        from executor.capability_contracts import CapabilityRequest
        assert CapabilityRequest is not None

    def test_capability_result_importable(self):
        from executor.capability_contracts import CapabilityResult
        assert CapabilityResult is not None

    def test_capability_type_importable(self):
        from executor.capability_contracts import CapabilityType
        assert CapabilityType is not None

    def test_capability_request_instantiates(self):
        from executor.capability_contracts import CapabilityRequest, CapabilityType
        req = CapabilityRequest(
            capability_id="test_tool",
            capability_type=CapabilityType.NATIVE_TOOL,
            action="run",
            params={"key": "value"},
            context={},
        )
        assert req.capability_id == "test_tool"

    def test_capability_result_failure_has_ok_false(self):
        """CapabilityResult uses .ok (not .success) as the boolean field."""
        from executor.capability_contracts import CapabilityResult, CapabilityType
        result = CapabilityResult.failure(
            CapabilityType.NATIVE_TOOL, "test_tool", "error message", ms=10
        )
        assert result.ok is False

    def test_capability_result_success_has_ok_true(self):
        from executor.capability_contracts import CapabilityResult, CapabilityType
        result = CapabilityResult.success(
            CapabilityType.NATIVE_TOOL, "test_tool", {"output": "ok"}, ms=10
        )
        assert result.ok is True


# ══════════════════════════════════════════════════════════════════════════════
# G. CIRCUIT BREAKER STATE MACHINE
# ══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerStateMachine:
    """Full circuit breaker state-machine coverage."""

    def _cb(self, threshold=3, reset_s=60.0):
        from core.meta_orchestrator import _CircuitBreaker
        return _CircuitBreaker(failure_threshold=threshold, reset_s=reset_s)

    def test_closed_after_success_clears_failures(self):
        cb = self._cb(threshold=2)
        cb.record_failure()  # 1 failure
        cb.record_success()  # reset
        cb.record_failure()  # 1 failure again (not 2)
        assert cb.is_open is False

    def test_opens_exactly_at_threshold_not_before(self):
        cb = self._cb(threshold=5)
        for i in range(4):
            cb.record_failure()
            assert cb.is_open is False, f"Opened too early at failure {i+1}"
        cb.record_failure()  # 5th failure
        assert cb.is_open is True

    def test_status_open_field_matches_is_open(self):
        cb = self._cb(threshold=1)
        cb.record_failure()
        status = cb.status()
        assert status["open"] == cb.is_open

    def test_failure_count_in_status(self):
        cb = self._cb(threshold=10)
        for _ in range(3):
            cb.record_failure()
        assert cb.status()["failures"] == 3

    def test_reset_zeroes_failures(self):
        cb = self._cb(threshold=10)
        for _ in range(5):
            cb.record_failure()
        cb.record_success()
        assert cb.status()["failures"] == 0
        assert cb.status()["open"] is False

    def test_probe_allowed_after_reset_s(self):
        """After reset_s elapses, circuit must allow one probe (auto-reset)."""
        cb = self._cb(threshold=1, reset_s=0.05)
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.1)
        # First check: circuit should be closed again (probe allowed)
        assert cb.is_open is False
        # Failure count should be zeroed
        assert cb.status()["failures"] == 0
