"""Outil HTTP — requêtes web contrôlées."""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_MAX_RESPONSE_BYTES = 1_000_000


class HttpGetTool(BEATool):
    name = "http_get"
    description = "Effectue une requête HTTP GET et retourne le corps de la réponse."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        url: str
        headers: dict[str, str] | None = None
        timeout: float = _TIMEOUT

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=input.timeout, follow_redirects=True) as client:
                resp = await client.get(input.url, headers=input.headers or {})
                content = resp.text[:_MAX_RESPONSE_BYTES]
                return ToolResult.ok(
                    output=content,
                    status_code=resp.status_code,
                    url=str(resp.url),
                )
        except httpx.TimeoutException:
            return ToolResult.fail(f"Timeout GET {input.url}")
        except Exception as e:
            return ToolResult.fail(f"HTTP GET failed: {e}")


class HttpPostTool(BEATool):
    name = "http_post"
    description = "Effectue une requête HTTP POST avec body JSON."
    permission = PermissionLevel.REQUIRES_APPROVAL

    class InputSchema(BaseModel):
        url: str
        body: dict
        headers: dict[str, str] | None = None
        timeout: float = _TIMEOUT

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=input.timeout) as client:
                resp = await client.post(
                    input.url,
                    json=input.body,
                    headers=input.headers or {},
                )
                return ToolResult.ok(
                    output=resp.text[:_MAX_RESPONSE_BYTES],
                    status_code=resp.status_code,
                )
        except Exception as e:
            return ToolResult.fail(f"HTTP POST failed: {e}")
