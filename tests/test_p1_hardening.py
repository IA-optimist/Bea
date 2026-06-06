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
        "mcp/hexstrike_v2/core/process_manager.py",
        "adapters/openhands_client.py",
    ):
        content = Path(path).read_text(encoding="utf-8")
        assert "shell=True" not in content, path
        assert "create_subprocess_shell" not in content, path
        assert '"/bin/bash", "-c"' not in content, path


@pytest.mark.asyncio
async def test_action_executor_rejects_paths_outside_workspace(monkeypatch, tmp_path):
    from core.state import ActionSpec, RiskLevel
    from executor import runner

    base = tmp_path / "p1-runner"
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


def test_local_fallback_sandbox_rejects_shell_metacharacters(monkeypatch, tmp_path):
    from executor.desktop_env.sandbox import LocalFallbackSandbox

    workspace = tmp_path / "p1-local-sandbox"
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


def test_v3_routes_use_header_aware_auth_dependency():
    for path in (
        "api/routes/business.py",
        "api/routes/economic.py",
        "api/routes/execution.py",
        "api/routes/models.py",
    ):
        content = Path(path).read_text(encoding="utf-8")
        assert "Depends(_check_auth)" not in content, path
        assert "_auth = Depends(_check_auth)" not in content, path


def test_prometheus_metrics_requires_auth():
    content = Path("api/main.py").read_text(encoding="utf-8")
    metrics_pos = content.index('@app.get("/metrics", include_in_schema=False)')
    handler = content[metrics_pos: metrics_pos + 220]

    assert "Depends(require_auth)" in handler


def test_hexstrike_v2_avoids_pickle_and_shell_invocation():
    cache_content = Path("mcp/hexstrike_v2/core/cache.py").read_text(encoding="utf-8")
    process_content = Path("mcp/hexstrike_v2/core/process_manager.py").read_text(encoding="utf-8")

    assert "import pickle" not in cache_content
    assert "pickle.load" not in cache_content
    assert "pickle.dump" not in cache_content
    assert "shell=True" not in process_content


def test_api_main_uses_lifespan_instead_of_on_event():
    content = Path("api/main.py").read_text(encoding="utf-8")

    assert "lifespan=" in content
    assert "@app.on_event" not in content


def test_readiness_is_fail_fast_in_production(monkeypatch):
    from api.routes import system_readiness

    monkeypatch.setenv("JARVIS_PRODUCTION", "true")
    payload = system_readiness.build_readiness_payload(
        mounted_paths={"/health"},
        expected_components={"health": "/health", "missing": "/missing"},
    )

    assert payload["ready"] is False
    assert payload["components"]["failed_list"] == ["missing"]


def test_docker_configs_use_canonical_dockerfile():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    prod = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    deploy = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    api_block = compose.split("  api:", 1)[1].split("  frontend:", 1)[0]

    assert "dockerfile: docker/Dockerfile" in api_block
    assert "dockerfile: docker/Dockerfile" in prod
    assert "-f docker/Dockerfile" in deploy
    assert "-f docker/Dockerfile" in ci
    assert "Dockerfile.nonroot" not in deploy
    assert "~/.jarvismax:/root/.jarvismax" not in compose


def test_requirements_txt_is_fully_pinned_and_lock_matches_direct_pins():
    txt_lines = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    lock_lines = Path("requirements.lock").read_text(encoding="utf-8").splitlines()
    direct_pins = {}
    lock_pins = {}

    for line in txt_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert ">=" not in line and "~=" not in line and ">" not in line, line
        assert "==" in line, line
        name, version = line.split("==", 1)
        name = name.split("[", 1)[0]
        direct_pins[name.lower()] = version.split(";", 1)[0].strip()

    for line in lock_lines:
        line = line.strip()
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==", 1)
            lock_pins[name.lower()] = version.split(";", 1)[0].strip()

    for name, version in direct_pins.items():
        assert lock_pins.get(name) == version, name

def test_static_api_token_uses_constant_time_compare():
    content = Path("api/auth.py").read_text(encoding="utf-8")

    assert "token_str == settings.jarvis_api_token" not in content
    assert "compare_digest" in content


def test_compose_does_not_expose_internal_services_or_use_latest_images():
    for path in ("docker-compose.yml", "docker-compose.prod.yml"):
        content = Path(path).read_text(encoding="utf-8")
        assert ":latest" not in content, path

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for port in ("5432", "6379", "6333", "6334", "11434"):
        assert f'"{port}:{port}"' not in compose
        assert f'"127.0.0.1:{port}:{port}"' in compose

def test_legacy_rate_limiters_do_not_trust_x_forwarded_for_by_default():
    # Audit Mo5: api/middleware/rate_limiter.py is now a deprecation shim that
    # re-exports the canonical implementation in api/rate_limiter.py, so the
    # TRUSTED_PROXY_IPS regression check only needs to apply to the canonical
    # file. If the shim is restored to a full implementation, re-add it here.
    content = Path("api/rate_limiter.py").read_text(encoding="utf-8")
    assert '.split(",")[0]' not in content
    assert "TRUSTED_PROXY_IPS" in content

    # And the deprecation shim must keep emitting a DeprecationWarning so
    # forgotten imports surface loudly.
    shim = Path("api/middleware/rate_limiter.py").read_text(encoding="utf-8")
    assert "DeprecationWarning" in shim
    assert "DEPRECATED" in shim

def test_require_auth_static_token_uses_constant_time_compare():
    content = Path("api/_deps.py").read_text(encoding="utf-8")

    assert "token == _API_TOKEN" not in content
    assert "hmac.compare_digest" in content

def test_models_routes_do_not_return_200_error_payloads():
    content = Path("api/routes/models.py").read_text(encoding="utf-8")

    assert 'return {"error"' not in content
    assert ', "error":' not in content
    assert '"ok": False' not in content
    assert "HTTPException" in content

def test_voice_webhook_is_not_documented_as_public_without_signature_verification():
    content = Path("api/routes/voice.py").read_text(encoding="utf-8")

    assert "dependencies=[Depends(_auth)]" in content
    assert "no auth" not in content.lower()
    assert "unauthenticated" not in content.lower()
