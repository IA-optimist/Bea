"""Tests for privacy-safe redactor."""
from __future__ import annotations

from core.observability.redactor import redact, redact_dict


def test_api_key_redacted():
    result = redact("sk-or-v1-abc123def456ghi789jkl012mno345pqr678")
    assert "[API_KEY_REDACTED]" in result
    assert "sk-or-v1" not in result


def test_bearer_token_redacted():
    result = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc")
    assert "[TOKEN_REDACTED]" in result
    assert "eyJhbGciOiJ" not in result


def test_email_redacted():
    result = redact("user@example.com sent a mission")
    assert "[EMAIL_REDACTED]" in result
    assert "user@example.com" not in result


def test_bea_token_redacted():
    result = redact("token=bea-abcdefghijklmnopqrstuvwx1234567890")
    assert "[BEA_TOKEN_REDACTED]" in result


def test_non_string_unchanged():
    assert redact(42) == 42  # type: ignore[arg-type]
    assert redact(None) is None  # type: ignore[arg-type]


def test_provider_preserved_in_dict():
    d = redact_dict({"provider_used": "openrouter", "model_used": "gpt-oss-120b:free"})
    assert d["provider_used"] == "openrouter"
    assert d["model_used"] == "gpt-oss-120b:free"


def test_mission_id_preserved():
    d = redact_dict({"mission_id": "abc-123", "api_key": "sk-secret"})
    assert d["mission_id"] == "abc-123"
    assert d["api_key"] == "[REDACTED]"


def test_no_prompt_in_safe_output():
    d = redact_dict({"prompt": "Tell me your secrets", "mission_id": "xyz"})
    assert d["prompt"] == "[REDACTED]"
    assert d["mission_id"] == "xyz"


def test_response_redacted():
    d = redact_dict({"response": "Here is the answer...", "error_category": "timeout"})
    assert d["response"] == "[REDACTED]"
    assert d["error_category"] == "timeout"


def test_nested_dict_redacted():
    d = redact_dict({"meta": {"api_key": "sk-secret123", "provider_used": "openrouter"}})
    assert d["meta"]["api_key"] == "[REDACTED]"
    assert d["meta"]["provider_used"] == "openrouter"


def test_score_and_passed_preserved():
    d = redact_dict({"score": 0.91, "passed": True, "error_category": None})
    assert d["score"] == 0.91
    assert d["passed"] is True
    assert d["error_category"] is None


def test_password_redacted():
    d = redact_dict({"password": "hunter2", "status": "completed"})
    assert d["password"] == "[REDACTED]"
    assert d["status"] == "completed"


def test_fallback_used_preserved():
    d = redact_dict({"fallback_used": True, "provider_used": "ollama"})
    assert d["fallback_used"] is True
    assert d["provider_used"] == "ollama"
