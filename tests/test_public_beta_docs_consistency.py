"""Tests for public beta docs consistency — ensure no stale or dangerous claims."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_readme_says_developer_preview():
    """README_PUBLIC_BETA.md must say 'Developer Preview'."""
    content = _read("README_PUBLIC_BETA.md")
    assert "Developer Preview" in content


def test_readme_does_not_say_rate_limiting_missing():
    """README must not claim rate-limiting is missing (it's implemented)."""
    content = _read("README_PUBLIC_BETA.md")
    # Check for stale claims
    assert "Pas de rate-limiting" not in content
    assert "rate-limiting intégré" in content or "Rate-limiting intégré" in content


def test_no_production_ready_claims():
    """No public doc should claim 'production ready'."""
    forbidden = ["production ready", "production-ready", "stable public beta", "guaranteed uptime"]
    for doc in [
        "README_PUBLIC_BETA.md",
        "docs/BETA_TESTER_GUIDE.md",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/SECURITY_MODEL.md",
        "docs/ALPHA_READINESS.md",
    ]:
        content = _read(doc)
        for phrase in forbidden:
            lines = content.splitlines()
            for line in lines:
                lower = line.lower().strip()
                # Skip lines that are negating the phrase (e.g., "not production ready")
                if f"not {phrase}" in lower or f"no {phrase}" in lower:
                    continue
                if phrase in lower:
                    pytest.fail(f"Forbidden phrase '{phrase}' in {doc}: {line.strip()}")


def test_no_cors_wildcard_recommended_in_docs():
    """Docs should not recommend CORS wildcard."""
    for doc in [
        "README_PUBLIC_BETA.md",
        "docs/SECURITY_MODEL.md",
        "docs/TROUBLESHOOTING.md",
        "docs/ENVIRONMENT.md",
    ]:
        content = _read(doc)
        lines = content.splitlines()
        for line in lines:
            lower = line.lower()
            if "bea_cors_origins=*" in lower:
                # OK if it's in a "blocked" or "never" context
                assert any(w in lower for w in ["block", "never", "forbidden", "not use", "must not"]), \
                    f"CORS wildcard mentioned without warning in {doc}: {line.strip()}"


def test_no_real_secrets_in_docs():
    """No real API keys in public docs."""
    secret_patterns = [
        re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
        re.compile(r"sk-ant-[A-Za-z0-9]{20,}"),
        re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    ]
    for doc in [
        "README_PUBLIC_BETA.md",
        "docs/BETA_TESTER_GUIDE.md",
        "docs/FEEDBACK_GUIDE.md",
        "docs/PRIVACY_FOR_TESTERS.md",
        "docs/KNOWN_LIMITATIONS.md",
        "docs/ENVIRONMENT.md",
    ]:
        content = _read(doc)
        for pattern in secret_patterns:
            assert pattern.findall(content) == [], f"Secret pattern in {doc}: {pattern.pattern}"


def test_readme_mentions_rate_limiting():
    """README should mention rate-limiting as implemented."""
    content = _read("README_PUBLIC_BETA.md")
    assert re.search(r"rate.limit|SlowAPI|BEA_RATE_LIMIT", content, re.IGNORECASE)


def test_env_docs_exist():
    """docs/ENVIRONMENT.md should exist and document key vars."""
    content = _read("docs/ENVIRONMENT.md")
    for var in ["BEA_PRODUCTION", "BEA_RATE_LIMIT_ENABLED", "BEA_CORS_ORIGINS", "BEA_SECRET_KEY"]:
        assert var in content, f"docs/ENVIRONMENT.md missing variable: {var}"
