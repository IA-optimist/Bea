"""Tests for core/circuit_breaker.py — CircuitBreaker pattern."""
import pytest
from unittest.mock import AsyncMock


def test_import():
    pass


def test_initial_state_closed():
    from core.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker("test", failure_threshold=3, cooldown_s=60)
    assert cb.state == CircuitState.CLOSED
    assert cb.is_closed
    assert not cb.is_open


def test_get_stats():
    from core.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker("stats-test")
    stats = cb.get_stats()
    assert stats["name"] == "stats-test"
    assert stats["state"] == "closed"
    assert stats["failure_count"] == 0
    assert stats["total_calls"] == 0


@pytest.mark.asyncio
async def test_success_keeps_closed():
    from core.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker("test-success", failure_threshold=3)
    async with cb.guard():
        pass  # success
    assert cb.state == CircuitState.CLOSED
    assert cb.get_stats()["total_calls"] == 1


@pytest.mark.asyncio
async def test_failures_open_circuit():
    from core.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker("test-fail", failure_threshold=2, cooldown_s=60)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with cb.guard():
                raise RuntimeError("boom")
    assert cb.state == CircuitState.OPEN
    assert cb.is_open


@pytest.mark.asyncio
async def test_open_circuit_raises_circuit_open_error():
    from core.circuit_breaker import CircuitBreaker, CircuitOpenError
    cb = CircuitBreaker("test-open", failure_threshold=1, cooldown_s=999)
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail")
    # Now circuit is open
    with pytest.raises(CircuitOpenError) as exc_info:
        async with cb.guard():
            pass
    assert "test-open" in str(exc_info.value)


@pytest.mark.asyncio
async def test_reset():
    from core.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker("test-reset", failure_threshold=1, cooldown_s=999)
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail")
    assert cb.is_open
    cb.reset()
    assert cb.is_closed


@pytest.mark.asyncio
async def test_call_wrapper():
    from core.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker("test-call", failure_threshold=3)
    mock_fn = AsyncMock(return_value="result")
    result = await cb.call(mock_fn, "arg1", key="val")
    assert result == "result"
    mock_fn.assert_called_once_with("arg1", key="val")


def test_get_breaker_singleton():
    from core.circuit_breaker import get_breaker
    cb1 = get_breaker("singleton-test")
    cb2 = get_breaker("singleton-test")
    assert cb1 is cb2


def test_get_breaker_different_names():
    from core.circuit_breaker import get_breaker
    cb1 = get_breaker("name-a")
    cb2 = get_breaker("name-b")
    assert cb1 is not cb2
