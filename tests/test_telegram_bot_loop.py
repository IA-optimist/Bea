from __future__ import annotations

import asyncio

import pytest

import scripts.run_telegram_bea as tg
from gateway.base import MessageEvent


class _FakeAdapter:
    base_url = "http://telegram.local"


class _FakeTGTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._message_id = 0

    async def __call__(self, _client, _base_url: str, method: str, payload: dict):
        self.calls.append((method, dict(payload)))
        if method == "sendMessage":
            self._message_id += 1
            return {"message_id": self._message_id}
        if method == "editMessageText":
            return True
        if method == "sendChatAction":
            return True
        return None


class _BlockingRunner:
    def __init__(self, responses: dict[str, str | None] | None = None) -> None:
        self.calls: list[str] = []
        self.started: dict[str, asyncio.Event] = {}
        self.release: dict[str, asyncio.Event] = {}
        self.responses = responses or {}

    async def handle(self, event: MessageEvent) -> str:
        self.calls.append(event.chat_id)
        started = self.started.setdefault(event.chat_id, asyncio.Event())
        release = self.release.setdefault(event.chat_id, asyncio.Event())
        started.set()
        await release.wait()
        return self.responses.get(event.chat_id, f"ok:{event.text}")


class _ErrorRunner(_BlockingRunner):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    async def handle(self, event: MessageEvent) -> str:
        self.calls.append(event.chat_id)
        started = self.started.setdefault(event.chat_id, asyncio.Event())
        started.set()
        await asyncio.sleep(0)
        raise self.exc


class _Client:
    pass


@pytest.fixture(autouse=True)
def _clean_registry():
    tg._active_chat_tasks.clear()
    yield
    tg._active_chat_tasks.clear()


def _event(chat_id: str, text: str = "bonjour", user_id: str = "u1") -> MessageEvent:
    return MessageEvent(platform="telegram", user_id=user_id, chat_id=chat_id, text=text)


async def _wait_started(runner: _BlockingRunner, chat_id: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 1
    while chat_id not in runner.started:
        if loop.time() >= deadline:
            raise TimeoutError(chat_id)
        await asyncio.sleep(0)
    remaining = max(0.0, deadline - loop.time())
    await asyncio.wait_for(runner.started[chat_id].wait(), timeout=remaining)


def test_same_chat_refuses_second_message(monkeypatch, capfd):
    transport = _FakeTGTransport()
    runner = _BlockingRunner(responses={"chat-1": "reponse finale"})
    monkeypatch.setattr(tg, "_tg", transport)
    monkeypatch.setattr(tg, "_keep_typing", lambda *args, **kwargs: asyncio.sleep(0))

    async def _run():
        ok = await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-1", "premier"))
        assert ok is True
        task = tg._active_chat_tasks["chat-1"]
        await _wait_started(runner, "chat-1")
        refused = await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-1", "second"))
        assert refused is False
        runner.release["chat-1"].set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err
    assert runner.calls == ["chat-1"]
    assert any(call[0] == "sendMessage" and call[1]["text"].startswith("Je termine encore ta demande pr?c?dente") for call in transport.calls)
    assert "chat-1" not in tg._active_chat_tasks


def test_different_chats_can_run_in_parallel(monkeypatch, capfd):
    transport = _FakeTGTransport()
    runner = _BlockingRunner(responses={"chat-1": "ok1", "chat-2": "ok2"})
    monkeypatch.setattr(tg, "_tg", transport)
    monkeypatch.setattr(tg, "_keep_typing", lambda *args, **kwargs: asyncio.sleep(0))

    async def _run():
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-1", "a")) is True
        task1 = tg._active_chat_tasks["chat-1"]
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-2", "b")) is True
        task2 = tg._active_chat_tasks["chat-2"]
        await _wait_started(runner, "chat-1")
        await _wait_started(runner, "chat-2")
        assert set(runner.calls) == {"chat-1", "chat-2"}
        runner.release["chat-1"].set()
        runner.release["chat-2"].set()
        await asyncio.wait_for(asyncio.gather(task1, task2), timeout=1)

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err
    assert not any(call[0] == "sendMessage" and "demande pr?c?dente" in call[1]["text"] for call in transport.calls)
    assert not tg._active_chat_tasks


def test_runner_exception_logs_and_keeps_chat_reusable(monkeypatch, caplog, capfd):
    transport = _FakeTGTransport()
    runner = _ErrorRunner(RuntimeError("boom"))
    monkeypatch.setattr(tg, "_tg", transport)

    typing_started = asyncio.Event()
    typing_cancelled = asyncio.Event()

    async def fake_typing(*_args, **_kwargs):
        typing_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            typing_cancelled.set()
            raise

    monkeypatch.setattr(tg, "_keep_typing", fake_typing)

    async def _run():
        with caplog.at_level("WARNING"):
            assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-err", "boom")) is True
            task = tg._active_chat_tasks["chat-err"]
            await _wait_started(runner, "chat-err")
            await asyncio.wait_for(typing_started.wait(), timeout=1)
            await asyncio.wait_for(task, timeout=1)
        assert typing_cancelled.is_set()
        assert "chat-err" not in tg._active_chat_tasks
        assert any("telegram_handle_failed" in rec.message for rec in caplog.records)
        assert any(call[0] == "editMessageText" and call[1]["text"] == "Une erreur interne est survenue." for call in transport.calls)
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-err", "followup")) is True
        task2 = tg._active_chat_tasks["chat-err"]
        await asyncio.wait_for(task2, timeout=1)

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err


def test_send_reply_exception_is_caught_and_cleans_up(monkeypatch, caplog, capfd):
    transport = _FakeTGTransport()
    runner = _BlockingRunner(responses={"chat-send": "ok"})
    monkeypatch.setattr(tg, "_tg", transport)

    typing_started = asyncio.Event()
    typing_cancelled = asyncio.Event()

    async def fake_typing(*_args, **_kwargs):
        typing_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            typing_cancelled.set()
            raise

    async def boom_send_reply(*_args, **_kwargs):
        raise RuntimeError("send failed")

    monkeypatch.setattr(tg, "_keep_typing", fake_typing)
    monkeypatch.setattr(tg, "_send_reply", boom_send_reply)

    async def _run():
        with caplog.at_level("WARNING"):
            assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-send", "boom")) is True
            task = tg._active_chat_tasks["chat-send"]
            await _wait_started(runner, "chat-send")
            await asyncio.wait_for(typing_started.wait(), timeout=1)
            runner.release["chat-send"].set()
            await asyncio.wait_for(task, timeout=1)
        assert typing_cancelled.is_set()
        assert "chat-send" not in tg._active_chat_tasks
        assert any("telegram_reply_failed" in rec.message for rec in caplog.records)
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-send", "next")) is True
        task2 = tg._active_chat_tasks["chat-send"]
        runner.release.setdefault("chat-send", asyncio.Event()).set()
        await asyncio.wait_for(task2, timeout=1)

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err


def test_normal_completion_clears_registry_and_edits_placeholder(monkeypatch, capfd):
    transport = _FakeTGTransport()
    runner = _BlockingRunner(responses={"chat-ok": "r?ponse finale"})
    monkeypatch.setattr(tg, "_tg", transport)
    monkeypatch.setattr(tg, "_keep_typing", lambda *args, **kwargs: asyncio.sleep(0))

    async def _run():
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-ok", "hello")) is True
        task = tg._active_chat_tasks["chat-ok"]
        await _wait_started(runner, "chat-ok")
        runner.release["chat-ok"].set()
        await asyncio.wait_for(task, timeout=1)
        assert "chat-ok" not in tg._active_chat_tasks
        assert any(call[0] == "editMessageText" and call[1]["text"] == "r?ponse finale" for call in transport.calls)
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-ok", "again")) is True
        task2 = tg._active_chat_tasks["chat-ok"]
        runner.release.setdefault("chat-ok", asyncio.Event()).set()
        await asyncio.wait_for(task2, timeout=1)

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err


def test_none_response_is_handled_without_error(monkeypatch, capfd):
    transport = _FakeTGTransport()
    runner = _BlockingRunner(responses={"chat-none": None})
    monkeypatch.setattr(tg, "_tg", transport)
    monkeypatch.setattr(tg, "_keep_typing", lambda *args, **kwargs: asyncio.sleep(0))

    async def _run():
        assert await tg._start_chat_message(runner, _Client(), _FakeAdapter(), _event("chat-none", "hello")) is True
        task = tg._active_chat_tasks["chat-none"]
        await _wait_started(runner, "chat-none")
        runner.release["chat-none"].set()
        await asyncio.wait_for(task, timeout=1)
        assert any(call[0] == "editMessageText" and call[1]["text"] == "(aucune r?ponse)" for call in transport.calls)
        assert "chat-none" not in tg._active_chat_tasks

    asyncio.run(_run())
    out = capfd.readouterr()
    assert "Task exception was never retrieved" not in out.err
