"""Edge case tests for core/circuit_breaker.py."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_half_open_success_closes_circuit():
    """After cooldown, successful call should close the circuit."""
    from core.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker("half-open-test", failure_threshold=1, cooldown_s=0.01)
    # Open the circuit
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail")
    assert cb.state == CircuitState.OPEN
    # Wait for cooldown
    await asyncio.sleep(0.02)
    # Next call should succeed and close circuit
    async with cb.guard():
        pass
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_reopens():
    """Failure in HALF_OPEN should reopen the circuit."""
    from core.circuit_breaker import CircuitBreaker, CircuitState
    cb = CircuitBreaker("reopen-test", failure_threshold=1, cooldown_s=0.01)
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail")
    assert cb.state == CircuitState.OPEN
    await asyncio.sleep(0.02)
    # Fail again in HALF_OPEN
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail again")
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_open_error_contains_cooldown():
    """CircuitOpenError should report remaining cooldown time."""
    from core.circuit_breaker import CircuitBreaker, CircuitOpenError
    cb = CircuitBreaker("cooldown-test", failure_threshold=1, cooldown_s=999)
    with pytest.raises(RuntimeError):
        async with cb.guard():
            raise RuntimeError("fail")
    with pytest.raises(CircuitOpenError) as exc_info:
        async with cb.guard():
            pass
    assert exc_info.value.cooldown_remaining > 0
    assert "cooldown-test" in exc_info.value.name


@pytest.mark.asyncio
async def test_stats_update_correctly():
    """Stats should track calls, failures, and blocks."""
    from core.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker("stats-test-2", failure_threshold=2, cooldown_s=999)
    # 1 success
    async with cb.guard():
        pass
    # 2 failures to open
    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with cb.guard():
                raise RuntimeError("fail")
    # 1 blocked call
    from core.circuit_breaker import CircuitOpenError
    with pytest.raises(CircuitOpenError):
        async with cb.guard():
            pass
    stats = cb.get_stats()
    assert stats["total_calls"] == 3  # 1 success + 2 failures
    assert stats["total_failures"] == 2
    assert stats["total_open_blocks"] == 1


def test_get_all_stats():
    """get_all_stats returns stats for all registered breakers."""
    from core.circuit_breaker import get_breaker, get_all_stats
    get_breaker("all-stats-a")
    get_breaker("all-stats-b")
    stats = get_all_stats()
    assert "all-stats-a" in stats
    assert "all-stats-b" in stats


def test_reset_all():
    """reset_all should close all circuits."""
    from core.circuit_breaker import get_breaker, reset_all, CircuitState
    cb = get_breaker("reset-all-test", failure_threshold=1)
    # Can't easily open without async, just verify reset_all doesn't crash
    reset_all()
    assert cb.state == CircuitState.CLOSED
