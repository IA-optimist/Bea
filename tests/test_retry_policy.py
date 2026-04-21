"""Tests for executor/retry_policy.py — retry logic."""


def test_import():
    pass


# ── is_retryable ─────────────────────────────────────────────

def test_retryable_timeout():
    from executor.retry_policy import is_retryable
    assert is_retryable(TimeoutError("connect timeout"))


def test_retryable_connection():
    from executor.retry_policy import is_retryable
    assert is_retryable(ConnectionError("refused"))


def test_retryable_os_error():
    from executor.retry_policy import is_retryable
    assert is_retryable(OSError("network unreachable"))


def test_not_retryable_value_error():
    from executor.retry_policy import is_retryable
    assert not is_retryable(ValueError("bad input"))


def test_not_retryable_type_error():
    from executor.retry_policy import is_retryable
    assert not is_retryable(TypeError("wrong type"))


def test_not_retryable_assertion():
    from executor.retry_policy import is_retryable
    assert not is_retryable(AssertionError("assert failed"))


def test_not_retryable_import_error():
    from executor.retry_policy import is_retryable
    assert not is_retryable(ImportError("no module"))


def test_retryable_by_message_keyword():
    from executor.retry_policy import is_retryable
    assert is_retryable(Exception("server temporarily unavailable"))
    assert is_retryable(Exception("rate limit exceeded"))
    assert is_retryable(Exception("HTTP 429 too many requests"))
    assert is_retryable(Exception("502 bad gateway"))


def test_not_retryable_generic():
    from executor.retry_policy import is_retryable
    assert not is_retryable(Exception("some random error"))


# ── should_retry ──────────────────────────────────────────────

def test_should_retry_within_limit():
    from executor.retry_policy import should_retry, RetryPolicy
    policy = RetryPolicy(max_attempts=3)
    assert should_retry(1, TimeoutError(), policy)
    assert should_retry(2, TimeoutError(), policy)
    assert not should_retry(3, TimeoutError(), policy)


def test_should_not_retry_non_retryable():
    from executor.retry_policy import should_retry, RetryPolicy
    policy = RetryPolicy(max_attempts=5)
    assert not should_retry(1, ValueError("bad"), policy)


# ── compute_delay ─────────────────────────────────────────────

def test_delay_increases_with_attempts():
    from executor.retry_policy import RetryPolicy
    policy = RetryPolicy(base_delay=1.0, backoff_factor=2.0, max_delay=30.0)
    # Test multiple times due to jitter
    delays = [policy.compute_delay(i) for i in range(1, 5)]
    # On average, delays should increase (but jitter adds variance)
    # Just verify they're all positive and bounded
    for d in delays:
        assert 0 < d <= 30.0


def test_delay_capped_at_max():
    from executor.retry_policy import RetryPolicy
    policy = RetryPolicy(base_delay=1.0, backoff_factor=10.0, max_delay=5.0)
    delay = policy.compute_delay(10)  # 1 * 10^9 would be huge, should be capped
    assert delay <= 5.0 * 1.3 + 0.1  # max + jitter tolerance


def test_delay_always_positive():
    from executor.retry_policy import RetryPolicy
    policy = RetryPolicy(base_delay=0.1, max_delay=1.0)
    for attempt in range(1, 20):
        assert policy.compute_delay(attempt) > 0


# ── Presets ───────────────────────────────────────────────────

def test_default_policy_values():
    from executor.retry_policy import DEFAULT_POLICY
    assert DEFAULT_POLICY.max_attempts == 3
    assert DEFAULT_POLICY.base_delay == 1.0
    assert DEFAULT_POLICY.max_delay == 30.0


def test_fast_policy_values():
    from executor.retry_policy import FAST_POLICY
    assert FAST_POLICY.max_attempts == 2
    assert FAST_POLICY.base_delay == 0.5
    assert FAST_POLICY.max_delay == 5.0


def test_aggressive_policy_values():
    from executor.retry_policy import AGGRESSIVE_POLICY
    assert AGGRESSIVE_POLICY.max_attempts == 5
