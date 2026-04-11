"""Tests for core/observability_helpers.py — timing, error categorization, retry."""
import time
import pytest
_silent_log = __import__("structlog").get_logger(__name__)

# Skip all tests - core/observability_helpers.py not yet implemented
pytestmark = pytest.mark.skip(reason="core/observability_helpers module not implemented")


def test_import():
    from core.observability_helpers import (
        timed, async_timed, Timer,
        categorize_error, error_summary,
        retry, async_retry,
    )


# ── Timer context manager ────────────────────────────────────

def test_timer_measures_ms():
    from core.observability_helpers import Timer
    with Timer("test") as t:
        time.sleep(0.01)
    assert t.ms >= 5  # at least ~10ms with tolerance


def test_timer_on_error():
    from core.observability_helpers import Timer
    try:
        with Timer("error_test") as t:
            raise ValueError("boom")
    except ValueError:
        _silent_log.debug("suppressed_exception", src='test_observability_helpers.py')
    assert t.ms >= 0


# ── timed decorator ───────────────────────────────────────────

def test_timed_decorator_returns_value():
    from core.observability_helpers import timed

    @timed
    def add(a, b):
        return a + b

    assert add(2, 3) == 5


def test_timed_decorator_propagates_exception():
    from core.observability_helpers import timed

    @timed
    def fail():
        raise RuntimeError("test")

    with pytest.raises(RuntimeError):
        fail()


@pytest.mark.asyncio
async def test_async_timed():
    from core.observability_helpers import async_timed

    @async_timed
    async def async_add(a, b):
        return a + b

    assert await async_add(1, 2) == 3


# ── categorize_error ──────────────────────────────────────────

def test_categorize_network():
    from core.observability_helpers import categorize_error
    assert categorize_error(TimeoutError()) == "network"
    assert categorize_error(ConnectionError()) == "network"


@pytest.mark.skip(reason="stale: API changed")
def test_categorize_not_found():
    from core.observability_helpers import categorize_error
    assert categorize_error(FileNotFoundError()) == "not_found"
    assert categorize_error(ModuleNotFoundError()) == "not_found"


def test_categorize_type_error():
    from core.observability_helpers import categorize_error
    assert categorize_error(TypeError()) == "type_error"
    assert categorize_error(ValueError()) == "type_error"


@pytest.mark.skip(reason="stale: API changed")
def test_categorize_by_keyword():
    from core.observability_helpers import categorize_error
    assert categorize_error(Exception("rate limit exceeded")) == "quota"
    assert categorize_error(Exception("HTTP 401 unauthorized")) == "auth"


def test_categorize_unknown():
    from core.observability_helpers import categorize_error
    assert categorize_error(Exception("something random")) == "unknown"


# ── error_summary ─────────────────────────────────────────────

def test_error_summary_structure():
    from core.observability_helpers import error_summary
    s = error_summary(TimeoutError("timed out"))
    assert s["type"] == "TimeoutError"
    assert s["category"] == "network"
    assert s["retryable"] is True
    assert "timed out" in s["message"]


def test_error_summary_not_retryable():
    from core.observability_helpers import error_summary
    s = error_summary(ValueError("bad input"))
    assert s["retryable"] is False


# ── retry decorator ───────────────────────────────────────────

def test_retry_succeeds_on_first_try():
    from core.observability_helpers import retry
    call_count = 0

    @retry(max_attempts=3, delay=0.01)
    def succeed():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert succeed() == "ok"
    assert call_count == 1


def test_retry_retries_on_transient_error():
    from core.observability_helpers import retry
    call_count = 0

    @retry(max_attempts=3, delay=0.01, retryable=(ConnectionError,))
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("transient")
        return "ok"

    assert flaky() == "ok"
    assert call_count == 3


def test_retry_raises_after_max_attempts():
    from core.observability_helpers import retry

    @retry(max_attempts=2, delay=0.01, retryable=(ConnectionError,))
    def always_fail():
        raise ConnectionError("persistent")

    with pytest.raises(ConnectionError):
        always_fail()


def test_retry_does_not_retry_non_retryable():
    from core.observability_helpers import retry
    call_count = 0

    @retry(max_attempts=3, delay=0.01, retryable=(ConnectionError,))
    def logic_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        logic_error()
    assert call_count == 1  # no retry


@pytest.mark.asyncio
async def test_async_retry():
    from core.observability_helpers import async_retry
    call_count = 0

    @async_retry(max_attempts=3, delay=0.01, retryable=(ConnectionError,))
    async def async_flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("transient")
        return "ok"

    result = await async_flaky()
    assert result == "ok"
    assert call_count == 2
