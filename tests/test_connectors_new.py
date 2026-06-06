"""Tests des nouveaux connecteurs — réseau/SMTP mockés, registre réel."""
from __future__ import annotations

import connectors.api_connectors as api
from connectors.api_connectors import SlackConnector, TelegramConnector
from connectors.base import ConnectorRegistry
from connectors.bootstrap import register_builtin_connectors
from connectors.dynamic_connector import (
    DynamicConnector,
    SpecError,
    register_connector_from_spec,
)


def _mock_http(monkeypatch, status=200, body="ok"):
    calls = []
    def fake(method, url, headers=None, json_body=None, timeout=15):
        calls.append({"method": method, "url": url, "headers": headers, "body": json_body})
        return status, body
    monkeypatch.setattr(api, "_http_request", fake)
    return calls


def test_slack_inert_without_config(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert SlackConnector().is_configured() is False
    res = SlackConnector().execute("send_message", {"text": "hi"})
    assert res.success is False and "manquant" in res.error


def test_slack_sends_when_configured(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    calls = _mock_http(monkeypatch, 200, "ok")
    res = SlackConnector().execute("send_message", {"text": "coucou"})
    assert res.success is True
    assert calls[0]["url"] == "https://hooks.slack.com/x"
    assert calls[0]["body"] == {"text": "coucou"}


def test_telegram_builds_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    calls = _mock_http(monkeypatch, 200, "ok")
    res = TelegramConnector().execute("send_message", {"chat_id": "42", "text": "yo"})
    assert res.success is True
    assert calls[0]["url"].endswith("/botTOK/sendMessage")
    assert calls[0]["body"]["chat_id"] == "42"


def test_http_error_status_is_failure(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    _mock_http(monkeypatch, 500, "boom")
    res = SlackConnector().execute("send_message", {"text": "x"})
    assert res.success is False and "http_500" in res.error


def test_unknown_action(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    res = SlackConnector().execute("nope", {})
    assert res.success is False and "Unknown action" in res.error


# ── Connecteur dynamique (auto-extension) ──────────────────────────────

def test_dynamic_connector_register_and_call(monkeypatch):
    spec = {
        "name": "weather",
        "description": "Météo",
        "base_url": "https://api.weather.test",
        "auth_header": {"Authorization": "Bearer ${WEATHER_TOKEN}"},
        "actions": {"forecast": {"method": "GET", "path": "/v1/forecast/{city}"}},
    }
    monkeypatch.setenv("WEATHER_TOKEN", "abc")
    calls = _mock_http(monkeypatch, 200, "sunny")
    reg = ConnectorRegistry()
    conn = register_connector_from_spec(spec, reg)
    assert reg.get("weather") is conn
    res = reg.execute("weather", "forecast", {"city": "Paris"})
    assert res.success is True
    assert calls[0]["url"] == "https://api.weather.test/v1/forecast/Paris"
    assert calls[0]["headers"]["Authorization"] == "Bearer abc"


def test_dynamic_spec_validation():
    for bad in [
        {"name": "BAD NAME", "base_url": "https://x", "actions": {"a": {"path": "/"}}},
        {"name": "ok", "base_url": "http://insecure", "actions": {"a": {"path": "/"}}},
        {"name": "ok", "base_url": "https://x", "actions": {}},
    ]:
        try:
            DynamicConnector(bad)
            assert False, f"aurait dû lever: {bad}"
        except SpecError:
            pass


def test_dynamic_missing_path_param(monkeypatch):
    spec = {"name": "svc", "base_url": "https://api.x", "auth_header": {},
            "actions": {"get": {"method": "GET", "path": "/items/{id}"}}}
    _mock_http(monkeypatch)
    conn = DynamicConnector(spec)
    res = conn.execute("get", {})  # 'id' manquant
    assert res.success is False and "manquant" in res.error


def test_bootstrap_registers_builtins():
    reg = ConnectorRegistry()
    names = register_builtin_connectors(reg)
    for expected in ("slack", "telegram", "discord", "notion", "email"):
        assert expected in names
    assert reg.get("slack") is not None
