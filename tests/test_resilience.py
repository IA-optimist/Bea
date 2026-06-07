"""tests/test_resilience.py — Reliability hardening tests."""
import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl


class TestBeaError(unittest.TestCase):

    def test_from_exception(self):
        from core.resilience import BeaError
        err = BeaError.from_exception(TimeoutError("connection timed out"), "tool")
        self.assertEqual(err.code, "TOOL_TIMEOUT")
        self.assertEqual(err.component, "tool")
        self.assertTrue(err.retryable)

    def test_permission_error(self):
        from core.resilience import BeaError
        err = BeaError.from_exception(PermissionError("access denied"), "executor")
        self.assertEqual(err.code, "PERMISSION_DENIED")
        self.assertFalse(err.retryable)
        self.assertEqual(err.severity, "HIGH")

    def test_parse_error(self):
        from core.resilience import BeaError
        err = BeaError.from_exception(ValueError("json parse failed"), "api")
        self.assertEqual(err.code, "PARSE_ERROR")

    def test_to_dict(self):
        from core.resilience import BeaError
        err = BeaError(code="TEST", message="test error", component="test")
        d = err.to_dict()
        self.assertIn("code", d)
        self.assertIn("message", d)
        self.assertIn("component", d)


class TestCircuitBreaker(unittest.TestCase):

    def test_starts_closed(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker()
        self.assertTrue(cb.can_execute("web_search"))
        self.assertEqual(cb.get_status("web_search"), "CLOSED")

    def test_opens_after_threshold(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure("bad_tool")
        self.assertFalse(cb.can_execute("bad_tool"))
        self.assertEqual(cb.get_status("bad_tool"), "OPEN")

    def test_closes_on_success(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("tool")
        cb.record_failure("tool")
        cb.record_success("tool")
        self.assertTrue(cb.can_execute("tool"))

    def test_half_open_after_recovery(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure("tool")
        cb.record_failure("tool")
        self.assertFalse(cb.can_execute("tool"))
        time.sleep(0.15)
        self.assertTrue(cb.can_execute("tool"))  # HALF_OPEN
        self.assertEqual(cb.get_status("tool"), "HALF_OPEN")

    def test_half_open_reopens_on_failure(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure("tool")
        cb.record_failure("tool")
        time.sleep(0.15)
        cb.can_execute("tool")  # Transition to HALF_OPEN
        cb.record_failure("tool")  # Fail again
        self.assertEqual(cb.get_status("tool"), "OPEN")

    def test_stats(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure("t1")
        cb.record_success("t2")
        stats = cb.stats()
        self.assertIn("t1", stats)

    def test_different_tools_independent(self):
        from core.resilience import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("a")
        cb.record_failure("a")
        self.assertFalse(cb.can_execute("a"))
        self.assertTrue(cb.can_execute("b"))


class TestContextGuard(unittest.TestCase):

    def test_short_text_unchanged(self):
        from core.resilience import guard_context
        text = "Hello world"
        self.assertEqual(guard_context(text), text)

    def test_long_text_truncated(self):
        from core.resilience import guard_context
        text = "x" * 100000
        result = guard_context(text, max_chars=1000)
        self.assertLess(len(result), 1200)
        self.assertIn("truncated", result)

    def test_preserves_start_and_end(self):
        from core.resilience import guard_context
        text = "START" + "x" * 50000 + "END"
        result = guard_context(text, max_chars=1000)
        self.assertTrue(result.startswith("START"))
        self.assertTrue(result.endswith("END"))


class TestTimeoutGuard(unittest.TestCase):

    def test_no_timeout(self):
        from core.resilience import timeout_guard
        result = timeout_guard(max_seconds=120, start_time=time.time())
        self.assertIsNone(result)

    def test_timeout_exceeded(self):
        from core.resilience import timeout_guard
        result = timeout_guard(max_seconds=1, start_time=time.time() - 5)
        self.assertIsNotNone(result)
        self.assertIn("timeout", result)

    def test_no_start_time(self):
        from core.resilience import timeout_guard
        result = timeout_guard(max_seconds=1, start_time=0)
        self.assertIsNone(result)


class TestIdempotency(unittest.TestCase):

    def test_same_input_same_key(self):
        from core.resilience import idempotency_key
        k1 = idempotency_key("web_search", {"query": "test"})
        k2 = idempotency_key("web_search", {"query": "test"})
        self.assertEqual(k1, k2)

    def test_different_input_different_key(self):
        from core.resilience import idempotency_key
        k1 = idempotency_key("web_search", {"query": "test"})
        k2 = idempotency_key("web_search", {"query": "other"})
        self.assertNotEqual(k1, k2)


class TestGracefulDegradation(unittest.TestCase):

    def test_returns_fallback_on_error(self):
        from core.resilience import degrade_gracefully

        @degrade_gracefully("test_op", fallback_value="fallback", log_error=False)
        def failing_func():
            raise RuntimeError("boom")

        result = failing_func()
        self.assertEqual(result, "fallback")

    def test_returns_normal_on_success(self):
        from core.resilience import degrade_gracefully

        @degrade_gracefully("test_op", fallback_value="fallback", log_error=False)
        def ok_func():
            return "success"

        result = ok_func()
        self.assertEqual(result, "success")


class TestProtectedPaths(unittest.TestCase):

    def test_new_critical_modules_protected(self):
        from core.self_improvement.protected_paths import PROTECTED_FILES_ARCH
        critical = [
            "core/schemas/final_output.py",
            "core/actions/action_model.py",
            "core/observability/event_envelope.py",
            "core/security/startup_guard.py",
            "core/policy/policy_engine.py",
            "core/resilience.py",
        ]
        for path in critical:
            self.assertIn(path, PROTECTED_FILES_ARCH,
                         f"CRITICAL: {path} must be in PROTECTED_FILES_ARCH")


if __name__ == "__main__":
    unittest.main()
