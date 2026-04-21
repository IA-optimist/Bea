"""
tests/test_readiness_endpoint.py — Pass 34: /api/v3/system/readiness tests

Covers:
  R1.  Endpoint registered on the convergence router at correct path
  R2.  Returns HTTP 200 when all probes pass
  R3.  Returns HTTP 503 when no LLM key configured
  R4.  Returns HTTP 503 when Qdrant unreachable
  R5.  Returns HTTP 503 when MetaOrchestrator init fails
  R6.  Response body structure is correct (ok, ready, status, probes keys)
  R7.  Probe dict contains llm_key, qdrant, orchestrator keys
  R8.  status field is 'ready' on 200, 'not_ready' on 503
  R10. ok field in response body matches HTTP status code
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock



# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_settings(openai_key="", anthropic_key="", qdrant_host="qdrant", qdrant_port=6333,
                   openrouter_key=""):
    s = MagicMock()
    s.openai_api_key = openai_key
    s.anthropic_api_key = anthropic_key
    # Must set explicitly — MagicMock auto-creates truthy child Mocks for unknown attrs
    s.openrouter_api_key = openrouter_key
    s.qdrant_host = qdrant_host
    s.qdrant_port = qdrant_port
    return s


def _parse(response):
    """Extract (status_code, body_dict) from a JSONResponse."""
    return response.status_code, json.loads(response.body)


def _patch_context(settings_mock, socket_result=0, orchestrator_ok=True):
    """Return a list of context managers to apply for system_readiness() tests."""
    mock_sock = MagicMock()
    mock_sock.connect_ex.return_value = socket_result
    mock_sock_class = MagicMock(return_value=mock_sock)

    mock_mo = MagicMock()
    mock_mo._circuit_breaker.status.return_value = {"open": False}

    mo_kwargs = {}
    if orchestrator_ok:
        mo_kwargs["return_value"] = mock_mo
    else:
        mo_kwargs["side_effect"] = RuntimeError("Orchestrator boot failed")

    return [
        patch("socket.socket", mock_sock_class),
        patch("config.settings.get_settings", return_value=settings_mock),
        patch("core.meta_orchestrator.get_meta_orchestrator", **mo_kwargs),
    ]


# ─── R1: Router registration ──────────────────────────────────────────────────

def test_R1_endpoint_registered():
    """GET /api/v3/system/readiness must be registered on the convergence router."""
    from api.routes.convergence import router
    paths = [r.path for r in router.routes]
    assert "/api/v3/system/readiness" in paths, f"Missing. Got: {paths}"


# ─── R2–R10: Response contract (async, using asyncio_mode=auto) ───────────────

class TestReadinessEndpoint:

    async def _run(self, settings_mock, socket_result=0, orchestrator_ok=True):
        from api.routes.convergence import system_readiness
        patches = _patch_context(settings_mock, socket_result, orchestrator_ok)
        for p in patches:
            p.start()
        try:
            return await system_readiness()
        finally:
            for p in patches:
                p.stop()

    async def test_R2_all_probes_pass_returns_200(self):
        resp = await self._run(_make_settings(openai_key="sk-test"))
        status, body = _parse(resp)
        assert status == 200, f"Expected 200, got {status}: {body}"

    async def test_R3_no_llm_key_returns_503(self):
        resp = await self._run(_make_settings(openai_key="", anthropic_key=""))
        status, _ = _parse(resp)
        assert status == 503

    async def test_R4_qdrant_unreachable_returns_503(self):
        resp = await self._run(_make_settings(openai_key="sk-test"), socket_result=111)
        status, _ = _parse(resp)
        assert status == 503

    async def test_R5_orchestrator_fail_returns_503(self):
        resp = await self._run(_make_settings(openai_key="sk-test"), orchestrator_ok=False)
        status, _ = _parse(resp)
        assert status == 503

    async def test_R6_response_body_structure(self):
        resp = await self._run(_make_settings(openai_key="sk-test"))
        _, outer = _parse(resp)
        assert "ok" in outer
        data = outer.get("data", outer)
        for key in ("ready", "status", "probes"):
            assert key in data, f"Missing key '{key}' in data: {data}"

    async def test_R7_probe_keys_present(self):
        resp = await self._run(_make_settings(openai_key="sk-test"))
        _, outer = _parse(resp)
        probes = outer.get("data", outer).get("probes", {})
        for key in ("llm_key", "qdrant", "orchestrator"):
            assert key in probes, f"Missing probe '{key}': {probes}"

    async def test_R8_status_ready_on_200(self):
        resp = await self._run(_make_settings(openai_key="sk-test"))
        status, outer = _parse(resp)
        assert status == 200
        assert outer.get("data", outer)["status"] == "ready"

    async def test_R8_status_not_ready_on_503(self):
        resp = await self._run(_make_settings(openai_key="", anthropic_key=""))
        status, outer = _parse(resp)
        assert status == 503
        assert outer.get("data", outer)["status"] == "not_ready"

    async def test_R10_ok_true_on_200(self):
        resp = await self._run(_make_settings(openai_key="sk-test"))
        status, body = _parse(resp)
        assert status == 200 and body["ok"] is True

    async def test_R10_ok_false_on_503(self):
        resp = await self._run(_make_settings(openai_key="", anthropic_key=""))
        status, body = _parse(resp)
        assert status == 503 and body["ok"] is False

    async def test_anthropic_key_satisfies_llm_check(self):
        """anthropic_api_key alone qualifies — no openai key needed."""
        resp = await self._run(_make_settings(openai_key="", anthropic_key="sk-ant-test"))
        status, _ = _parse(resp)
        assert status == 200
