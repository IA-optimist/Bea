"""Tests pour core.tools.code_execution_tool (Axe 3) — sandbox mocké, sans Docker."""
from __future__ import annotations

import core.tools.code_execution_tool as cet


class _FakeSandbox:
    def __init__(self, exit_code: int = 0, output: str = "hello\n") -> None:
        self._exit = exit_code
        self._output = output
        self.started = False
        self.stopped = False
        self.executed: str | None = None

    def start(self) -> None:
        self.started = True

    def execute(self, cmd: str):
        self.executed = cmd
        return self._exit, self._output

    def stop(self) -> None:
        self.stopped = True


def test_empty_code_returns_error():
    res = cet.execute_code("   ")
    assert res["ok"] is False
    assert res["error"] == "empty_code"


def test_successful_execution(monkeypatch, tmp_path):
    fake = _FakeSandbox(exit_code=0, output="42\n")
    monkeypatch.setattr(cet, "_get_sandbox", lambda wp: fake)
    res = cet.execute_code("print(42)", workspace_path=str(tmp_path))
    assert res["ok"] is True
    assert "42" in res["output"]
    assert fake.started and fake.stopped
    assert fake.executed.startswith("python .bea_exec_")
    # le script temporaire est nettoyé
    assert not any(p.name.startswith(".bea_exec_") for p in tmp_path.iterdir())


def test_nonzero_exit_is_error(monkeypatch, tmp_path):
    fake = _FakeSandbox(exit_code=1, output="Traceback (most recent call last)")
    monkeypatch.setattr(cet, "_get_sandbox", lambda wp: fake)
    res = cet.execute_code("raise SystemExit(1)", workspace_path=str(tmp_path))
    assert res["ok"] is False
    assert "exit_code=1" in res["error"]


def test_timeout_is_clamped(monkeypatch, tmp_path):
    fake = _FakeSandbox()
    monkeypatch.setattr(cet, "_get_sandbox", lambda wp: fake)
    res = cet.execute_code("print(1)", timeout=99999, workspace_path=str(tmp_path))
    assert res["ok"] is True


def test_output_is_truncated(monkeypatch, tmp_path):
    fake = _FakeSandbox(exit_code=0, output="x" * 50000)
    monkeypatch.setattr(cet, "_get_sandbox", lambda wp: fake)
    res = cet.execute_code("print('x'*50000)", workspace_path=str(tmp_path))
    assert res["ok"] is True
    assert len(res["output"]) <= 10000
