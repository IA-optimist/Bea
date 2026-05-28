"""Tests for core._logging_helpers (M3 swallow helper)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from core._logging_helpers import swallow, swallowing


def _fake_log():
    """A logger stub that records (level, event, kwargs) on each call."""
    log = MagicMock()
    return log


def test_swallow_absorbs_exception_and_logs_warning_by_default():
    log = _fake_log()
    with swallow(log, action="test_action", agent="alpha"):
        raise RuntimeError("boom")
    log.warning.assert_called_once()
    call = log.warning.call_args
    assert call.args[0] == "swallowed_exception"
    assert call.kwargs["action"] == "test_action"
    assert call.kwargs["exc_type"] == "RuntimeError"
    assert call.kwargs["exc_msg"] == "boom"
    assert call.kwargs["agent"] == "alpha"


def test_swallow_does_not_log_when_no_exception():
    log = _fake_log()
    with swallow(log, action="quiet_path"):
        x = 1 + 1  # noqa
    log.warning.assert_not_called()
    log.error.assert_not_called()
    log.info.assert_not_called()


def test_swallow_level_error_uses_error_logger():
    log = _fake_log()
    with swallow(log, action="critical_bg", level="error"):
        raise ValueError("oops")
    log.error.assert_called_once()
    log.warning.assert_not_called()


def test_swallow_level_info_uses_info_logger():
    log = _fake_log()
    with swallow(log, action="cleanup", level="info"):
        raise OSError("missing file")
    log.info.assert_called_once()


def test_swallow_rejects_debug_level():
    log = _fake_log()
    with pytest.raises(ValueError, match="not allowed"):
        with swallow(log, action="bad", level="debug"):
            pass


def test_swallow_requires_action():
    log = _fake_log()
    with pytest.raises(ValueError, match="required"):
        with swallow(log, action=""):
            pass


def test_swallow_passes_keyboardinterrupt_through():
    log = _fake_log()
    with pytest.raises(KeyboardInterrupt):
        with swallow(log, action="busy_loop"):
            raise KeyboardInterrupt
    log.warning.assert_not_called()


def test_swallow_passes_systemexit_through():
    log = _fake_log()
    with pytest.raises(SystemExit):
        with swallow(log, action="shutdown"):
            raise SystemExit(0)
    log.warning.assert_not_called()


def test_swallow_truncates_long_exception_message():
    log = _fake_log()
    msg = "X" * 1000
    with swallow(log, action="overflow"):
        raise RuntimeError(msg)
    captured = log.warning.call_args.kwargs["exc_msg"]
    assert len(captured) <= 200


def test_swallowing_decorator_absorbs_and_returns_none():
    log = _fake_log()

    @swallowing(log, action="boom_fn")
    def doomed():
        raise RuntimeError("nope")

    result = doomed()
    assert result is None
    log.warning.assert_called_once()


def test_swallowing_decorator_returns_value_on_success():
    log = _fake_log()

    @swallowing(log, action="ok_fn")
    def ok():
        return 42

    assert ok() == 42
    log.warning.assert_not_called()
