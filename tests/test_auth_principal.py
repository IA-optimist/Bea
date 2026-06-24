"""
Tests for api/auth_principal.py — canonical authenticated principal extraction.
"""
from __future__ import annotations

import pytest
from fastapi import Request
from starlette.datastructures import State

from api.auth_principal import build_principal_id, get_authenticated_principal


class _FakeRequest:
    """Minimal request stand-in for unit tests."""

    def __init__(self, user: dict | None = None):
        self.state = State()
        if user is not None:
            self.state.user = user


@pytest.mark.parametrize(
    "user,expected",
    [
        ({"username": "admin", "role": "admin", "auth_type": "jwt"}, "jwt:admin"),
        ({"username": "alice", "role": "user", "auth_type": "jwt"}, "jwt:alice"),
        ({"sub": "bob", "role": "user", "auth_type": "jwt"}, "jwt:bob"),
        ({"username": "api", "role": "admin", "auth_type": "static"}, "static:api"),
        (
            {"username": "partner-token", "role": "user", "auth_type": "access_token", "token_id": "tok-123"},
            "access_token:tok-123",
        ),
        ({"auth_type": "service"}, "service:unknown"),
        ({}, "unknown:unknown"),
    ],
)
def test_build_principal_id_non_secret(user, expected):
    assert build_principal_id(user) == expected
    # Secret/token values must never leak through the principal id.
    assert "secret" not in expected.lower()
    assert "jwt-token-value" not in expected


def test_build_principal_id_prefers_token_id_for_access_token():
    user = {
        "username": "display-name",
        "role": "user",
        "auth_type": "access_token",
        "token_id": "tok-abc-uuid",
    }
    principal = build_principal_id(user)
    assert principal == "access_token:tok-abc-uuid"
    assert "display-name" not in principal


def test_get_authenticated_principal_from_request_state():
    request = _FakeRequest({"username": "admin", "role": "admin", "auth_type": "static"})
    assert get_authenticated_principal(request) == "static:admin"


def test_get_authenticated_principal_returns_none_without_auth():
    request = _FakeRequest()
    assert get_authenticated_principal(request) is None


def test_get_authenticated_principal_rejects_fake_principal_id_in_params():
    # Params are not consulted by the helper. Only request.state.user matters.
    request = _FakeRequest({"username": "alice", "role": "user", "auth_type": "jwt"})
    principal = get_authenticated_principal(request)
    assert principal == "jwt:alice"
