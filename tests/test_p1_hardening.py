from pathlib import Path

import pytest


def test_tool_executor_rejects_shell_metacharacters(monkeypatch):
    from core.tool_executor import run_shell_command

    monkeypatch.delenv("JARVIS_EXECUTION_DISABLED", raising=False)
    monkeypatch.setenv("JARVIS_SHELL_ALLOWLIST", "1")

    result = run_shell_command("ls | whoami")

    assert result["ok"] is False
    assert "shell_metacharacters" in result["error"]


def test_executors_do_not_use_shell_invocation():
    for path in (
        "core/tool_executor.py",
        "executor/runner.py",
        "executor/desktop_env/sandbox.py",
    ):
        content = Path(path).read_text(encoding="utf-8")
        assert "shell=True" not in content, path
        assert "create_subprocess_shell" not in content, path
        assert '"/bin/bash", "-c"' not in content, path


@pytest.mark.asyncio
async def test_action_executor_rejects_paths_outside_workspace(monkeypatch):
    from core.state import ActionSpec, RiskLevel
    from executor import runner

    base = Path(".pytest_cache/p1-runner").resolve()
    workspace = base / "workspace"
    outside = base / "outside.txt"
    workspace.mkdir(parents=True, exist_ok=True)
    outside.write_text("outside", encoding="utf-8")

    monkeypatch.setattr(runner, "WORKSPACE", workspace)
    monkeypatch.setattr(runner, "BACKUP_DIR", workspace / ".backups")
    monkeypatch.setattr(runner, "LOGS_DIR", workspace / "logs")
    monkeypatch.setattr(runner, "EXEC_LOG", workspace / "logs" / "executor.jsonl")

    executor = runner.ActionExecutor()
    result = await executor.execute(
        ActionSpec(
            id="p1",
            action_type="read_file",
            target=str(outside),
            risk=RiskLevel.LOW,
        )
    )

    assert result.success is False
    assert "outside workspace" in (result.error or "")


def test_local_fallback_sandbox_rejects_shell_metacharacters(monkeypatch):
    from executor.desktop_env.sandbox import LocalFallbackSandbox

    workspace = Path(".pytest_cache/p1-local-sandbox").resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JARVIS_ALLOW_LOCAL_SANDBOX", "1")

    sandbox = LocalFallbackSandbox(str(workspace))
    code, output = sandbox.execute("echo ok && echo pwned")

    assert code == -1
    assert "shell_metacharacters" in output


def test_api_main_mounts_only_slowapi_rate_limiter():
    content = Path("api/main.py").read_text(encoding="utf-8")

    assert "app.state.limiter = limiter" in content
    assert "app.add_exception_handler(RateLimitExceeded" in content
    assert "app.add_middleware(SlowAPIMiddleware)" in content
    assert "app.add_middleware(RateLimitMiddleware)" not in content
    assert "from api.rate_limiter import RateLimitMiddleware" not in content


def test_api_main_adds_cors_after_security_middlewares():
    content = Path("api/main.py").read_text(encoding="utf-8")

    access_pos = content.index("app.add_middleware(AccessEnforcementMiddleware)")
    slowapi_pos = content.index("app.add_middleware(SlowAPIMiddleware)")
    security_pos = content.index("app.add_middleware(SecurityHeadersMiddleware)")
    cors_pos = content.index("app.add_middleware(\n    CORSMiddleware")

    assert access_pos < slowapi_pos < security_pos < cors_pos
