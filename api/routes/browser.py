"""
BEA MAX — Browser API Routes (Phase 8)

POST /api/v2/browser/navigate   — navigate to URL, optionally extract text
POST /api/v2/browser/search     — web search, return top 10 results
POST /api/v2/browser/screenshot — navigate to URL, return base64 screenshot
"""
from __future__ import annotations

import os
from typing import Optional

import structlog
from fastapi import Depends, APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from api._deps import _check_auth

log = structlog.get_logger(__name__)


def _auth(x_bea_token: str | None = Header(None),
          authorization: str | None = Header(None)):
    _check_auth(x_bea_token, authorization)



router = APIRouter(prefix="/api/v2/browser", tags=["browser"], dependencies=[Depends(_auth)])

_API_TOKEN = os.getenv("BEA_API_TOKEN", "")


# ── Request models ────────────────────────────────────────────

class NavigateRequest(BaseModel):
    url:          str  = Field(..., min_length=4)
    extract_text: bool = False


class SearchRequest(BaseModel):
    query:  str = Field(..., min_length=1)
    engine: str = "duckduckgo"


class ScreenshotRequest(BaseModel):
    url: str = Field(..., min_length=4)


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/navigate")
async def browser_navigate(
    req: NavigateRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Navigate to a URL and optionally extract visible page text."""
    from tools.browser_tool import BrowserTool

    async with BrowserTool() as browser:
        nav = await browser.navigate(req.url)
        if not nav.success:
            raise HTTPException(status_code=502, detail=nav.error)
        data = dict(nav.data or {})
        if req.extract_text:
            txt = await browser.get_text()
            data["text"] = (txt.data or {}).get("text", "") if txt.success else ""
        return {"ok": True, "data": data}


@router.post("/search")
async def browser_search(
    req: SearchRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Search the web and return top 10 results {title, url, snippet}."""
    from tools.browser_tool import BrowserTool

    async with BrowserTool() as browser:
        result = await browser.search_web(req.query, engine=req.engine)
        if not result.success:
            raise HTTPException(status_code=502, detail=result.error)
        return {"ok": True, "data": result.data}


@router.post("/screenshot")
async def browser_screenshot(
    req: ScreenshotRequest,
    x_bea_token: Optional[str] = Header(None),
):
    """Navigate to URL and return a base64-encoded PNG screenshot."""
    from tools.browser_tool import BrowserTool

    async with BrowserTool() as browser:
        nav = await browser.navigate(req.url)
        if not nav.success:
            raise HTTPException(status_code=502, detail=nav.error)
        shot = await browser.screenshot()
        if not shot.success:
            raise HTTPException(status_code=502, detail=shot.error)
        return {"ok": True, "data": shot.data}
