import pytest

from core.policy_engine import reset_policy_engine


@pytest.fixture(autouse=True)
def _reset_policy_engine_singleton():
    """Reset the shared PolicyEngine singleton around every test."""
    reset_policy_engine()
    yield
    reset_policy_engine()
