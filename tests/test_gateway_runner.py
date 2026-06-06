"""Tests pour gateway.runner / gateway.base — fake adapter + handler, sans réseau."""
from __future__ import annotations

import asyncio

from gateway.base import MessageEvent, PlatformAdapter
from gateway.runner import GatewayRunner


class _FakeAdapter(PlatformAdapter):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id, text):
        self.sent.append((chat_id, text))


def _event(user="u1", text="bonjour"):
    return MessageEvent(platform="fake", user_id=user, chat_id="c1", text=text)


def test_session_key():
    assert _event().session_key() == "fake:c1"


def test_handler_invoked_and_response():
    runner = GatewayRunner(handler=lambda e: f"echo:{e.text}")
    out = asyncio.run(runner.handle(_event(text="salut")))
    assert out == "echo:salut"


def test_async_handler():
    async def h(e):
        return "async-ok"
    runner = GatewayRunner(handler=h)
    assert asyncio.run(runner.handle(_event())) == "async-ok"


def test_allowlist_denies_unknown_user():
    runner = GatewayRunner(handler=lambda e: "ok", allowlist={"alice"})
    assert asyncio.run(runner.handle(_event(user="bob"))) == "Accès non autorisé."
    assert asyncio.run(runner.handle(_event(user="alice"))) == "ok"


def test_none_allowlist_allows_all():
    runner = GatewayRunner(handler=lambda e: "ok")  # allowlist None
    assert asyncio.run(runner.handle(_event(user="anyone"))) == "ok"


def test_handler_error_is_caught():
    def boom(e):
        raise RuntimeError("down")
    runner = GatewayRunner(handler=boom)
    assert asyncio.run(runner.handle(_event())) == "Une erreur interne est survenue."


def test_dispatch_sends_via_adapter():
    adapter = _FakeAdapter()
    runner = GatewayRunner(handler=lambda e: f"re:{e.text}")
    runner.register(adapter)
    out = asyncio.run(runner.dispatch(_event(text="ping")))
    assert out == "re:ping"
    assert adapter.sent == [("c1", "re:ping")]


def test_dispatch_unauthorized_still_replies_but_no_crash():
    adapter = _FakeAdapter()
    runner = GatewayRunner(handler=lambda e: "ok", allowlist=set())  # personne autorisé
    runner.register(adapter)
    out = asyncio.run(runner.dispatch(_event()))
    assert out == "Accès non autorisé."
    assert adapter.sent == [("c1", "Accès non autorisé.")]
