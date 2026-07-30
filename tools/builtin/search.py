"""Outil recherche web via DuckDuckGo (pas de clé API requise)."""
from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BEATool):
    name = "web_search"
    description = "Recherche sur le web et retourne les N premiers résultats."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        query: str
        max_results: int = 5

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        url = "https://api.duckduckgo.com/"
        params = {"q": input.query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
            results = []
            for r in data.get("RelatedTopics", [])[: input.max_results]:
                if "Text" in r and "FirstURL" in r:
                    results.append({"title": r["Text"], "url": r["FirstURL"]})
            return ToolResult.ok(output=results, query=input.query, count=len(results))
        except Exception as e:
            return ToolResult.fail(f"Web search failed: {e}")
