"""
Browser Bridge — adapts tools/browser_tool.py (async BaseTool)
to core/tool_executor.py (sync function dict).

Bridges the gap between the two tool systems without modifying either.
Each function wraps the async BrowserTool method in asyncio.run().

Safety: all operations go through ToolExecutor's kill switch + approval gating.
The bridge adds login detection for automatic approval escalation.
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger("jarvis.tools.browser_bridge")
log = logger  # M3 emitter alias

# ── Lazy singleton ────────────────────────────────────────────────────────────

_browser_tool = None
_loop = None


def _get_browser():
    """Lazy-init BrowserTool singleton."""
    global _browser_tool
    if _browser_tool is None:
        try:
            from tools.browser_tool import BrowserTool
            _browser_tool = BrowserTool(allow_dangerous=False)
        except ImportError as e:
            logger.warning("BrowserTool import failed: %s", e)
            raise
    return _browser_tool


def _run_async(coro):
    """Run async coroutine from a sync context (safe from any context).
    Uses get_running_loop() to detect an active loop; falls back to asyncio.run().
    """
    try:
        asyncio.get_running_loop()
        # Already in async context — run in a dedicated thread to avoid nesting
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=60)
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        return asyncio.run(coro)


# ── Login detection ───────────────────────────────────────────────────────────

_LOGIN_PATTERNS = re.compile(
    r"(login|sign.?in|password|oauth|authenticate|credentials|log.?in)",
    re.IGNORECASE,
)


def _detect_login(url: str, page_text: str = "") -> bool:
    """Detect if a page involves authentication."""
    if _LOGIN_PATTERNS.search(url):
        return True
    if page_text and _LOGIN_PATTERNS.search(page_text[:2000]):
        return True
    return False


# ── Bridge functions (sync, dict return) ──────────────────────────────────────

def browser_navigate(url: str = "", **kwargs) -> dict:
    """Navigate to URL. Returns {"ok", "result", "error"}."""
    if not url:
        return {"ok": False, "result": "", "error": "url required"}

    # Block internal addresses
    for blocked in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.", "10.", "172.16.", "192.168."):  # nosec B104 — SSRF blocklist, not a bind
        if blocked in url:
            return {"ok": False, "result": "", "error": f"blocked: internal address {blocked}"}

    try:
        bt = _get_browser()
        result = _run_async(bt.navigate(url))
        if result.success:
            # Check for login page
            title = result.data.get("title", "")
            if _detect_login(url, title):
                logger.info("browser_login_detected: %s", url)
                return {
                    "ok": True,
                    "result": result.data,
                    "error": "",
                    "warning": "login_page_detected",
                    "requires_approval": True,
                }
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_get_text(selector: str = "body", **kwargs) -> dict:
    """Extract text from CSS selector on current page."""
    try:
        bt = _get_browser()
        result = _run_async(bt.get_text(selector))
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_click(selector: str = "", **kwargs) -> dict:
    """Click element on current page. Risk: SUPERVISED."""
    if not selector:
        return {"ok": False, "result": "", "error": "selector required"}
    try:
        bt = _get_browser()
        result = _run_async(bt.click(selector))
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_fill(selector: str = "", value: str = "", **kwargs) -> dict:
    """Fill form field on current page. Risk: SUPERVISED."""
    if not selector:
        return {"ok": False, "result": "", "error": "selector required"}
    try:
        bt = _get_browser()
        result = _run_async(bt.fill_form(selector, value))
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_screenshot(path: str = "", **kwargs) -> dict:
    """Take screenshot of current page."""
    try:
        bt = _get_browser()
        result = _run_async(bt.screenshot(path or None))
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_extract_links(**kwargs) -> dict:
    """Extract all links from current page."""
    try:
        bt = _get_browser()
        result = _run_async(bt.extract_links())
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_search(query: str = "", engine: str = "duckduckgo", **kwargs) -> dict:
    """Search the web via browser. Returns structured results."""
    if not query:
        return {"ok": False, "result": "", "error": "query required"}
    try:
        bt = _get_browser()
        result = _run_async(bt.search_web(query, engine))
        if result.success:
            return {"ok": True, "result": result.data, "error": ""}
        return {"ok": False, "result": "", "error": result.error}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)[:200]}


def browser_close(**kwargs) -> dict:
    """Close browser instance."""
    global _browser_tool
    if _browser_tool:
        try:
            _run_async(_browser_tool.close())
        except Exception as _exc:
            log.warning("swallowed_exception", action="browser_bridge_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
        _browser_tool = None
    return {"ok": True, "result": "browser_closed", "error": ""}


# ── Registration helper ──────────────────────────────────────────────────────

BROWSER_TOOLS = {
    "browser_navigate":      browser_navigate,
    "browser_get_text":      browser_get_text,
    "browser_click":         browser_click,
    "browser_fill":          browser_fill,
    "browser_screenshot":    browser_screenshot,
    "browser_extract_links": browser_extract_links,
    "browser_search":        browser_search,
    "browser_close":         browser_close,
}

BROWSER_TOOL_TIMEOUTS = {
    "browser_navigate": 35,
    "browser_get_text": 10,
    "browser_click": 15,
    "browser_fill": 10,
    "browser_screenshot": 15,
    "browser_extract_links": 10,
    "browser_search": 40,
    "browser_close": 5,
}

BROWSER_TOOL_REQUIRED_PARAMS = {
    "browser_navigate": ["url"],
    "browser_get_text": [],
    "browser_click": ["selector"],
    "browser_fill": ["selector", "value"],
    "browser_screenshot": [],
    "browser_extract_links": [],
    "browser_search": ["query"],
    "browser_close": [],
}

BROWSER_ACTION_TYPES = {
    "browser_navigate": "network",
    "browser_get_text": "read",
    "browser_click": "network_write",
    "browser_fill": "network_write",
    "browser_screenshot": "read",
    "browser_extract_links": "read",
    "browser_search": "network",
    "browser_close": "read",
}
