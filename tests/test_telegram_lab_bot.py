from __future__ import annotations

from pathlib import Path

from integrations.telegram_lab_bot import (
    BackendFailure,
    BackendResult,
    TelegramLabBot,
    TelegramLabConfig,
    build_lab_goal,
)


class _FakeOpenClawBackend:
    def __init__(self, text: str = "", error: str = ""):
        self.text = text
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def run(self, agent_id: str, message: str) -> BackendResult:
        self.calls.append((agent_id, message))
        if self.error:
            raise BackendFailure(self.error)
        return BackendResult(backend="openclaw", text=self.text or "openclaw-ok")


class _FakeJarvisBackend:
    def __init__(self, text: str = "jarvis-ok"):
        self.text = text
        self.calls: list[str] = []

    def run(self, goal: str) -> BackendResult:
        self.calls.append(goal)
        return BackendResult(backend="jarvis", text=self.text)


def _make_config(tmp_path: Path, **overrides) -> TelegramLabConfig:
    values = {
        "telegram_bot_token": "token",
        "repo_root": tmp_path,
        "state_file": tmp_path / "telegram-state.json",
    }
    values.update(overrides)
    return TelegramLabConfig(**values)


def test_agent_command_updates_chat_state(tmp_path: Path):
    bot = TelegramLabBot(
        _make_config(tmp_path),
        openclaw_backend=_FakeOpenClawBackend(),
        jarvis_backend=_FakeJarvisBackend(),
    )

    replies = bot.handle_text("100", "200", "/agent architect")

    state = bot.state_store.get_chat_state("100")
    assert state.mode == "lab"
    assert state.agent == "lab-architect"
    assert any("lab-architect" in chunk for chunk in replies)


def test_auto_backend_falls_back_to_jarvis(tmp_path: Path):
    openclaw = _FakeOpenClawBackend(error="pairing required")
    jarvis = _FakeJarvisBackend(text="Jarvis fallback reply")
    bot = TelegramLabBot(
        _make_config(tmp_path),
        openclaw_backend=openclaw,
        jarvis_backend=jarvis,
    )

    replies = bot.handle_text("100", "200", "Design the MCP boundary")

    assert openclaw.calls == [("lab-director", "Design the MCP boundary")]
    assert jarvis.calls == [build_lab_goal("lab-director", "Design the MCP boundary")]
    assert replies[0].startswith("OpenClaw was unavailable")
    assert "Jarvis fallback reply" in "\n".join(replies)


def test_mission_command_uses_raw_jarvis_prompt(tmp_path: Path):
    jarvis = _FakeJarvisBackend(text="Mission complete")
    bot = TelegramLabBot(
        _make_config(tmp_path),
        openclaw_backend=_FakeOpenClawBackend(),
        jarvis_backend=jarvis,
    )

    replies = bot.handle_text("100", "200", "/mission Return only 42")

    assert jarvis.calls == ["Return only 42"]
    assert replies == ["Mission complete"]


def test_specialist_command_is_one_off_and_does_not_change_default_agent(tmp_path: Path):
    openclaw = _FakeOpenClawBackend(text="Architect answer")
    bot = TelegramLabBot(
        _make_config(tmp_path),
        openclaw_backend=openclaw,
        jarvis_backend=_FakeJarvisBackend(),
    )

    replies = bot.handle_text("100", "200", "/architect Map the orchestration path")

    assert openclaw.calls == [("lab-architect", "Map the orchestration path")]
    state = bot.state_store.get_chat_state("100")
    assert state.agent == "lab-director"
    assert replies == ["Architect answer"]


def test_denies_unauthorized_chat(tmp_path: Path):
    bot = TelegramLabBot(
        _make_config(tmp_path, allowed_chat_ids={"999"}),
        openclaw_backend=_FakeOpenClawBackend(),
        jarvis_backend=_FakeJarvisBackend(),
    )

    replies = bot.handle_text("100", "200", "hello")

    assert replies == ["Access denied for this chat."]


def test_config_accepts_legacy_telegram_target_chat_id(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_TARGET_CHAT_ID", "12345")

    config = TelegramLabConfig.from_env(repo_root=tmp_path)

    assert "12345" in config.allowed_chat_ids
