"""Tests pour ContextCompactor."""
import pytest

from core.orchestration.context_compactor import (
    ContextCompactor,
    Message,
    CompactionResult,
    DEFAULT_KEEP_RECENT,
)
from core.orchestration.message_converter import from_list, to_list


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_messages(n: int, chars_each: int = 1000) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant", content="x" * chars_each)
        for i in range(n)
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_token_estimate_heuristic():
    c = ContextCompactor("m1")
    msgs = [Message(role="user", content="a" * 400)]  # 400 chars → 100 tokens
    assert c.estimate_tokens(msgs) == 100


def test_needs_compaction_below_threshold():
    c = ContextCompactor("m1", token_threshold=10_000)
    msgs = make_messages(5, chars_each=100)  # 5 * 25 tokens = 125 tokens
    assert not c.needs_compaction(msgs)


def test_needs_compaction_above_threshold():
    c = ContextCompactor("m1", token_threshold=1_000)
    msgs = make_messages(5, chars_each=2_000)  # 5 * 500 tokens = 2500 tokens
    assert c.needs_compaction(msgs)


@pytest.mark.asyncio
async def test_maybe_compact_no_action_below_threshold():
    c = ContextCompactor("m1", token_threshold=100_000)
    msgs = make_messages(3, chars_each=100)
    result_msgs, result = await c.maybe_compact(msgs)
    assert result is None
    assert result_msgs is msgs  # même objet, pas de copie


@pytest.mark.asyncio
async def test_compact_reduces_message_count():
    c = ContextCompactor("m1", token_threshold=500, keep_recent=3)
    msgs = make_messages(15, chars_each=200)  # largement au-dessus du seuil
    compacted, result = await c.maybe_compact(msgs)

    assert result is not None
    assert result.compacted_count < result.original_count
    assert len(compacted) == 1 + 3  # 1 résumé + 3 récents
    assert compacted[0].role == "system"
    assert "[RÉSUMÉ" in compacted[0].content


@pytest.mark.asyncio
async def test_compact_keeps_recent_messages():
    c = ContextCompactor("m1", token_threshold=200, keep_recent=2)
    msgs = make_messages(10, chars_each=100)
    compacted, result = await c.maybe_compact(msgs)

    # Les 2 derniers messages originaux doivent être conservés
    assert compacted[-2].content == msgs[-2].content
    assert compacted[-1].content == msgs[-1].content


@pytest.mark.asyncio
async def test_compact_uses_llm_when_available():
    async def mock_llm(prompt: str) -> str:
        return "Résumé généré par LLM"

    c = ContextCompactor("m1", token_threshold=200, keep_recent=2, llm_client=mock_llm)
    msgs = make_messages(10, chars_each=100)
    compacted, result = await c.maybe_compact(msgs)

    assert result is not None
    assert "Résumé généré par LLM" in result.summary
    assert "Résumé généré par LLM" in compacted[0].content


@pytest.mark.asyncio
async def test_compact_stores_in_memory_facade():
    stored = []

    class MockFacade:
        async def store(self, collection, text, metadata):
            stored.append({"collection": collection, "text": text, "metadata": metadata})

    c = ContextCompactor("m1", token_threshold=200, keep_recent=2, memory_facade=MockFacade())
    msgs = make_messages(10, chars_each=100)
    _, result = await c.maybe_compact(msgs)

    assert result.stored_in_memory
    assert len(stored) == 1
    assert stored[0]["collection"] == "episodic"
    assert stored[0]["metadata"]["mission_id"] == "m1"


@pytest.mark.asyncio
async def test_compact_handles_memory_facade_error():
    class BrokenFacade:
        async def store(self, **kwargs):
            raise ConnectionError("Qdrant down")

    c = ContextCompactor("m1", token_threshold=200, keep_recent=2, memory_facade=BrokenFacade())
    msgs = make_messages(10, chars_each=100)
    compacted, result = await c.maybe_compact(msgs)

    # L'erreur Qdrant ne doit pas planter la compaction
    assert result is not None
    assert not result.stored_in_memory
    assert len(compacted) > 0


def test_message_converter_roundtrip():
    dicts = [
        {"role": "user", "content": "Bonjour"},
        {"role": "assistant", "content": "Salut", "extra": "meta"},
    ]
    messages = from_list(dicts)
    back = to_list(messages)
    assert back[0]["role"] == "user"
    assert back[0]["content"] == "Bonjour"
    assert back[1]["extra"] == "meta"
