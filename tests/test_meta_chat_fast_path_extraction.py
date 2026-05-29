"""Regression tests for MetaOrchestrator chat fast-path helpers."""
from pathlib import Path


def test_chat_fast_path_policy_has_dedicated_module():
    from core import meta_chat_fast_path as chat_fast_path

    assert chat_fast_path.should_skip_fast_path(
        "supprime ce fichier",
        needs_approval=False,
        risk_level="low",
    )
    assert chat_fast_path.should_skip_fast_path(
        "simple question",
        needs_approval=True,
        risk_level="low",
    )
    assert chat_fast_path.should_skip_fast_path(
        "simple question",
        needs_approval=False,
        risk_level="high",
    )
    assert not chat_fast_path.should_skip_fast_path(
        "simple question",
        needs_approval=False,
        risk_level="low",
    )

    prompt = chat_fast_path.build_fast_path_prompt(
        "Bonjour",
        memory="- souvenir",
        context="conversation",
    )
    assert "Mémoire pertinente" in prompt
    assert "Conversation récente" in prompt
    assert "Message: Bonjour" in prompt

    source = Path("core/meta_orchestrator.py").read_text(encoding="utf-8")
    assert "_DESTRUCTIVE_KW" not in source
    assert "FAST_CHAT_SYSTEM_PROMPT" not in source
