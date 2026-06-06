"""Tests pour gateway.platforms.webhook — parsing + envoi délégué, sans réseau."""
from __future__ import annotations

import asyncio

from gateway.platforms.webhook import WebhookAdapter
from gateway.runner import GatewayRunner


def test_parse_flat_payload():
    a = WebhookAdapter()
    ev = a.parse({"user_id": "u1", "chat_id": "c1", "text": "salut"})
    assert ev is not None
    assert ev.platform == "webhook" and ev.user_id == "u1" and ev.text == "salut"


def test_parse_nested_payload_with_custom_mapping():
    a = WebhookAdapter(user_field="message.from.id", chat_field="message.chat.id",
                       text_field="message.text")
    ev = a.parse({"message": {"from": {"id": 42}, "chat": {"id": 99}, "text": "hi"}})
    assert ev.user_id == "42" and ev.chat_id == "99" and ev.text == "hi"


def test_parse_ignores_empty_or_invalid():
    a = WebhookAdapter()
    assert a.parse({"user_id": "u", "text": ""}) is None
    assert a.parse("not a dict") is None


def test_send_uses_injected_sender():
    sent = []
    a = WebhookAdapter(sender=lambda chat, text: sent.append((chat, text)))
    asyncio.run(a.send("c1", "coucou"))
    assert sent == [("c1", "coucou")]


def test_end_to_end_with_runner():
    sent = []
    adapter = WebhookAdapter(sender=lambda c, t: sent.append((c, t)))
    runner = GatewayRunner(handler=lambda e: f"reçu: {e.text}")
    runner.register(adapter)
    ev = adapter.parse({"user_id": "u1", "chat_id": "c1", "text": "ping"})
    out = asyncio.run(runner.dispatch(ev))
    assert out == "reçu: ping"
    assert sent == [("c1", "reçu: ping")]
