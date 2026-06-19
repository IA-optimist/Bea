"""
Tests for T5.3 — DockerSandbox killswitch and execute() timeout.

Tests use the LocalFallbackSandbox (no Docker required) and the
DockerSandbox with a mock docker client to avoid Docker dependency.
"""
from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from executor.desktop_env.sandbox import DockerSandbox, LocalFallbackSandbox


# ── LocalFallbackSandbox — basic smoke (no Docker) ─────────────────────────

class TestLocalFallbackSandbox:

    def test_disabled_by_default(self, tmp_path: Path) -> None:
        sb = LocalFallbackSandbox(str(tmp_path))
        rc, out = sb.execute("echo hello")
        assert rc == -1
        assert "désactivé" in out.lower() or "desactive" in out.lower() or "BEA_ALLOW_LOCAL_SANDBOX" in out

    def test_enabled_runs_command(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BEA_ALLOW_LOCAL_SANDBOX", "1")
        sb = LocalFallbackSandbox(str(tmp_path))
        sb.start()
        rc, out = sb.execute("python -c \"print('hello')\"")
        assert rc == 0
        assert "hello" in out


# ── DockerSandbox killswitch — unit tests with mock ─────────────────────────

class TestDockerSandboxKillswitch:

    def _make_sandbox(self, tmp_path: Path) -> DockerSandbox:
        sb = DockerSandbox(str(tmp_path))
        # Mock the docker check so we don't need a real daemon
        sb._available = True
        sb._client = mock.MagicMock()
        return sb

    def _attach_container(self, sb: DockerSandbox) -> mock.MagicMock:
        container = mock.MagicMock()
        sb.container = container
        sb.container_id = "bea-sandbox-test"
        return container

    def test_execute_returns_output_on_success(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)
        container.exec_run.return_value = (0, b"hello\n")

        rc, out = sb.execute("echo hello")
        assert rc == 0
        assert "hello" in out

    def test_execute_returns_minus1_on_parse_error(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        self._attach_container(sb)
        rc, out = sb.execute("echo hello && echo world")  # metachar
        assert rc == -1
        assert "metachar" in out.lower() or "not_allowed" in out.lower()

    def test_execute_not_started_returns_error(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        # No container attached
        rc, out = sb.execute("echo hi")
        assert rc == -1

    def test_kill_sends_sigkill(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)

        sb.kill()

        container.kill.assert_called_once()
        assert sb.container is None

    def test_kill_when_no_container_is_noop(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        # No container — should not raise
        sb.kill()

    def test_kill_logs_error_on_docker_failure(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)
        container.kill.side_effect = RuntimeError("docker down")

        # Should not propagate — kill is best-effort
        sb.kill()
        assert sb.container is None  # cleared in finally

    def test_execute_timeout_fires_killswitch(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)

        import time

        def slow_exec(*args, **kwargs):
            time.sleep(10)  # exceeds timeout
            return (0, b"never reached")

        container.exec_run.side_effect = slow_exec

        rc, out = sb.execute("sleep 10", timeout=1)
        assert rc == -1
        assert "sandbox_killed" in out
        assert "1s" in out

    def test_execute_timeout_zero_means_no_limit(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)
        container.exec_run.return_value = (0, b"done")

        rc, out = sb.execute("echo done", timeout=0)
        assert rc == 0
        assert "done" in out

    def test_execute_exception_returns_error_tuple(self, tmp_path: Path) -> None:
        sb = self._make_sandbox(tmp_path)
        container = self._attach_container(sb)
        container.exec_run.side_effect = RuntimeError("container gone")

        rc, out = sb.execute("anything")
        assert rc == -1
        assert "container gone" in out
