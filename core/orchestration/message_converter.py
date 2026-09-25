"""Conversion entre les formats de messages Béa et Message dataclass."""
from __future__ import annotations

from core.orchestration.context_compactor import Message


def from_dict(d: dict) -> Message:
    """Convertit un dict {role, content, ...} en Message."""
    return Message(
        role=d.get("role", "user"),
        content=str(d.get("content", "")),
        metadata={k: v for k, v in d.items() if k not in ("role", "content")},
    )


def to_dict(m: Message) -> dict:
    """Convertit un Message en dict."""
    return m.to_dict()


def from_list(messages: list[dict]) -> list[Message]:
    return [from_dict(m) for m in messages]


def to_list(messages: list[Message]) -> list[dict]:
    return [to_dict(m) for m in messages]
