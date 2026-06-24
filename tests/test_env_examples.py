"""Tests for .env.example files — ensure no dangerous defaults leak."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Real secret patterns that must NEVER appear in example files
SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
]


@pytest.fixture
def local_env():
    return (ROOT / ".env.example.local").read_text(encoding="utf-8")


@pytest.fixture
def production_env():
    return (ROOT / ".env.example.production").read_text(encoding="utf-8")


@pytest.fixture
def env_example():
    return (ROOT / ".env.example").read_text(encoding="utf-8")


def test_local_env_not_production(local_env):
    """Local env example must not have BEA_PRODUCTION=true."""
    assert "BEA_PRODUCTION=true" not in local_env
    assert "BEA_PRODUCTION=false" in local_env


def test_production_env_has_required_vars(production_env):
    """Production env must have all required vars with CHANGE_ME placeholders."""
    required = [
        "BEA_PRODUCTION=true",
        "BEA_SECRET_KEY=CHANGE_ME",
        "BEA_API_TOKEN=CHANGE_ME",
        "BEA_ADMIN_PASSWORD=CHANGE_ME",
        "BEA_RATE_LIMIT_ENABLED=true",
        "BEA_CORS_ORIGINS=https://",
    ]
    for var in required:
        assert var in production_env, f"Missing required production var: {var}"


def test_no_real_secrets_in_any_env_example(local_env, production_env, env_example):
    """No real API keys or tokens in any env example file."""
    for content in [local_env, production_env, env_example]:
        for pattern in SECRET_PATTERNS:
            matches = pattern.findall(content)
            assert matches == [], f"Real secret pattern found in env example: {pattern.pattern}"


def test_no_cors_wildcard_recommended(local_env, production_env):
    """Neither local nor production env should recommend CORS wildcard."""
    assert "BEA_CORS_ORIGINS=*" not in local_env
    assert "BEA_CORS_ORIGINS=*" not in production_env


def test_production_env_has_rate_limit_enabled(production_env):
    """Production env must have rate-limiting enabled."""
    assert "BEA_RATE_LIMIT_ENABLED=true" in production_env


def test_local_env_has_rate_limit_enabled(local_env):
    """Local env should have rate-limiting enabled (can be higher limit)."""
    assert "BEA_RATE_LIMIT_ENABLED=true" in local_env


def test_env_example_points_to_templates(env_example):
    """The main .env.example should point to local and production templates."""
    assert ".env.example.local" in env_example
    assert ".env.example.production" in env_example


def test_no_skip_improvement_gate_set(local_env, production_env):
    """Neither template should set BEA_SKIP_IMPROVEMENT_GATE to a value."""
    # It's OK to mention it in comments, but not to set it
    for content in [local_env, production_env]:
        lines = [l.strip() for l in content.splitlines() if not l.strip().startswith("#")]
        for line in lines:
            if line.startswith("BEA_SKIP_IMPROVEMENT_GATE="):
                # Only acceptable if the value is empty
                assert line == "BEA_SKIP_IMPROVEMENT_GATE=", \
                    f"BEA_SKIP_IMPROVEMENT_GATE must not be set to a value: {line}"
