from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.routes import vault as vault_routes


class _FakeUseResult:
    success = True
    error = ""

    def safe_dict(self):
        return {"success": True}


class _FakeVault:
    def __init__(self):
        self.use_calls = []
        self.log_calls = []

    def use_secret(self, *args, **kwargs):
        self.use_calls.append((args, kwargs))
        return _FakeUseResult()

    def get_audit_logs(self, *args, **kwargs):
        self.log_calls.append((args, kwargs))
        return [{"event": "ok"}]


def test_vault_use_rejects_viewer_role():
    fake = _FakeVault()
    vault_routes.set_vault(fake)
    req = vault_routes.UseSecretRequest(
        secret_id="sec-1",
        agent_name="agent",
        target_domain="example.com",
    )

    with pytest.raises(HTTPException) as exc:
        vault_routes.use_secret(req, user={"role": "viewer"})

    assert exc.value.status_code == 403
    assert fake.use_calls == []


def test_vault_use_maps_api_user_to_operator_role():
    fake = _FakeVault()
    vault_routes.set_vault(fake)
    req = vault_routes.UseSecretRequest(
        secret_id="sec-1",
        agent_name="agent",
        target_domain="example.com",
    )

    assert vault_routes.use_secret(req, user={"role": "user"}) == {"success": True}
    assert fake.use_calls == [
        (("sec-1", "agent", "example.com", ""), {"role": "operator"})
    ]


def test_vault_logs_are_requested_with_admin_role():
    fake = _FakeVault()
    vault_routes.set_vault(fake)

    result = vault_routes.audit_logs(user={"role": "admin"})

    assert result == {"logs": [{"event": "ok"}], "count": 1}
    assert fake.log_calls == [((None, None, 100), {"role": "admin"})]


def test_start_with_deps_does_not_install_packages_at_runtime():
    content = open("start_with_deps.sh", encoding="utf-8").read()

    assert "pip install" not in content


def test_jwt_fallback_token_format_is_disabled(monkeypatch):
    from api import auth

    monkeypatch.setattr(auth, "_jwt", None, raising=False)

    with pytest.raises(RuntimeError, match="PyJWT"):
        auth.create_access_token({"sub": "admin", "role": "admin"})


class _FakeStripeRequest:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = headers

    async def body(self):
        return self._body


@pytest.mark.asyncio
async def test_stripe_webhook_rejects_missing_webhook_secret(monkeypatch):
    from api.routes import finance

    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(finance, "WEBHOOK_SECRET", "")
    request = _FakeStripeRequest(
        b'{"type":"unknown.event","data":{}}',
        {"stripe-signature": "t=1,v1=invalid"},
    )

    with pytest.raises(HTTPException) as exc:
        await finance.stripe_webhook(request)

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_stripe_webhook_rejects_missing_signature(monkeypatch):
    from api.routes import finance

    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(finance, "WEBHOOK_SECRET", "whsec_test")
    request = _FakeStripeRequest(b'{"type":"unknown.event","data":{}}', {})

    with pytest.raises(HTTPException) as exc:
        await finance.stripe_webhook(request)

    assert exc.value.status_code == 400


def test_hexstrike_vendored_module_is_removed():
    """Audit Sprint 3 P0 (2026-05-19): the entire vendored mcp/hexstrike-ai/
    tree was removed (~12k LOC, 0 import from the rest of the repo,
    RCE-by-design via subprocess shell=True in command_execution.py).
    The MCP registry entry is kept for capability metadata, but the
    vendored copy itself stays deleted. Re-vendoring would re-introduce
    the obfuscation + RCE surface this test originally guarded against."""
    assert not Path("mcp/hexstrike-ai").exists(), (
        "mcp/hexstrike-ai/ should remain deleted — install upstream "
        "(0x4m4/hexstrike-ai) in an isolated container if you need it."
    )


def test_missions_route_has_no_tmp_trace_logging():
    content = Path("api/routes/missions.py").read_text(encoding="utf-8")

    assert "bea_trace.log" not in content
    assert "TRACE_A" not in content
    assert "TRACE_B" not in content


def test_compose_files_do_not_mount_docker_socket():
    for path in ("docker-compose.override.yml", "docker-compose.prod.yml"):
        content = Path(path).read_text(encoding="utf-8")
        assert "/var/run/docker.sock" not in content


def test_monitoring_grafana_uses_env_configuration():
    content = Path("deploy/monitoring/docker-compose-monitoring.yml").read_text(encoding="utf-8")

    assert "beamax2026" not in content
    assert "72.62.177.55" not in content
    assert "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD" in content


def test_monitoring_tree_does_not_commit_grafana_secret_or_vps_ip():
    # Stack éclaté par la consolidation (2026-06) : configs/scripts dans
    # deploy/monitoring/, docs dans docs/monitoring/.
    scanned = 0
    for root in (Path("deploy/monitoring"), Path("docs/monitoring")):
        assert root.is_dir(), str(root)
        for path in root.rglob("*"):
            if path.is_file():
                scanned += 1
                content = path.read_text(encoding="utf-8", errors="ignore")
                assert "beamax2026" not in content, str(path)
                assert "72.62.177.55" not in content, str(path)
    assert scanned > 0


def test_deploy_runs_after_ci_success():
    content = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "workflow_run:" in content
    assert "github.event.workflow_run.conclusion == 'success'" in content
