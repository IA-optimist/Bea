from __future__ import annotations

import subprocess
import sys


def test_sandbox_uses_current_python_executable(monkeypatch, tmp_path) -> None:
    from core.self_improvement.sandbox_executor import SandboxExecutor

    commands: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        commands.append(list(cmd))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    executor = SandboxExecutor(tmp_path)
    executor.run_linter(str(tmp_path), ["example.py"])
    executor.run_tests(str(tmp_path), ["tests/test_example.py"])

    assert commands[0][0] == sys.executable
    assert commands[1][0] == sys.executable

