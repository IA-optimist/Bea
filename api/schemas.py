"""
BEA MAX — API response schema helpers.
"""
from __future__ import annotations
from typing import Any


def ok(data: Any = None) -> dict:
    """Standard success response."""
    return {"status": "ok", "data": data}


def error(msg: str, code: int = 400) -> dict:
    """Standard error response."""
    return {"status": "error", "message": msg, "code": code}
