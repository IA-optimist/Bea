"""
agent_runtime/sandbox.py — SandboxWrapper around executor/desktop_env/sandbox.py.

Provides a thin policy-aware wrapper so ACI actions go through the
existing DockerSandbox when available, falling back to a process-level
restricted runner.  Secrets are never injected into the sandbox.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any

import structlog

from agent_runtime.policy import SandboxPolicy

log = structlog.get_logger("bea.aci.sandbox")

_COMMAND_METACHARS = ("|", "&&", "||", ";", ">", "<", "`", "$(", "\n", "\r")


class SandboxResult:
    def __init__(self, returncode: int, stdout: str, stderr: str, duration_ms: int):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms

    @property
    def success(self) -> bool:
        return self.returncode == 0


class SandboxWrapper:
    """
    Wraps the existing DockerSandbox for ACI use.

    If Docker is available, delegates to DockerSandbox.
    Otherwise, runs in-process with a strict command whitelist.
    Secrets are never passed through; env is sanitised.
    """

    def __init__(self, policy: SandboxPolicy, workspace_path: str | Path):
        self.policy = policy
        self.workspace_path = Path(workspace_path)
        self._docker_sandbox: Any = None
        self._use_docker = self._try_init_docker()

    def _try_init_docker(self) -> bool:
        try:
            from executor.desktop_env.sandbox import DockerSandbox
            ds = DockerSandbox(str(self.workspace_path))
            if ds.is_available():
                self._docker_sandbox = ds
                return True
        except Exception as exc:
            log.debug("sandbox_docker_unavailable", reason=str(exc)[:80])
        return False

    def run(self, command: str, *, cwd: str | None = None) -> SandboxResult:
        """Run a whitelisted command inside the sandbox."""
        # Reject shell metacharacters
        if any(m in command for m in _COMMAND_METACHARS):
            return SandboxResult(1, "", "shell metacharacters not allowed", 0)

        args = command.split()
        if not args:
            return SandboxResult(1, "", "empty command", 0)

        bin_name = Path(args[0]).stem
        if bin_name not in self.policy.allowed_commands:
            return SandboxResult(
                1, "",
                f"command '{bin_name}' not in allowed_commands whitelist: {sorted(self.policy.allowed_commands)}",
                0,
            )

        t0 = time.monotonic()
        if self._use_docker and self._docker_sandbox:
            try:
                self._docker_sandbox.start()
                rc, output = self._docker_sandbox.execute(command)
                self._docker_sandbox.stop()
                ms = int((time.monotonic() - t0) * 1000)
                return SandboxResult(rc, output, "", ms)
            except Exception as exc:
                log.warning("sandbox_docker_exec_failed", error=str(exc)[:120])

        # Fallback: restricted subprocess (no shell, sanitised env)
        safe_env = {k: v for k, v in os.environ.items()
                    if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASS", "AUTH"))}
        try:
            result = subprocess.run(  # nosec B603
                args,
                cwd=cwd or str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=self.policy.timeout,
                env=safe_env,
            )
            ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(result.returncode, result.stdout, result.stderr, ms)
        except subprocess.TimeoutExpired:
            return SandboxResult(1, "", f"timeout after {self.policy.timeout}s", 0)
        except Exception as exc:
            return SandboxResult(1, "", str(exc), 0)
