"""
BEA MAX — BrowserTool (Phase 8)
Playwright-based browser automation with risk classification.

Risk levels per operation:
  navigate     → SAFE
  get_text     → SAFE
  screenshot   → SAFE
  extract_links→ SAFE
  search_web   → SAFE
  click        → SUPERVISED
  fill_form    → SUPERVISED
  execute_js   → DANGEROUS (requires allow_dangerous=True)
"""
from __future__ import annotations

import base64
import os
import tempfile
from typing import Optional

import structlog

from tools.base import BaseTool, ToolResult, ToolRisk

log = structlog.get_logger(__name__)

_TIMEOUT_MS = 30_000  # 30 s


class BrowserTool(BaseTool):
    name = "browser"
    risk = ToolRisk.SAFE

    def __init__(self, allow_dangerous: bool = False):
        self.allow_dangerous = allow_dangerous
        self._pw      = None
        self._browser = None
        self._context = None
        self._page    = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def _ensure_browser(self) -> None:
        """Lazy-init Playwright browser (headless Chromium)."""
        if self._browser is not None:
            return
        from playwright.async_api import async_playwright
        self._pw      = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
        )
        # Disable navigator.webdriver flag (stealth)
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self._page = await self._context.new_page()
        log.info("browser_init", headless=True)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page    = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    async def __aenter__(self):
        await self._ensure_browser()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ── Helper ────────────────────────────────────────────────

    async def _get_page(self):
        await self._ensure_browser()
        return self._page

    # ── Methods ───────────────────────────────────────────────

    async def navigate(self, url: str) -> ToolResult:
        """Go to URL and return page title + final URL. Risk: SAFE."""
        try:
            page = await self._get_page()
            await page.goto(url, timeout=_TIMEOUT_MS, wait_until="domcontentloaded")
            title     = await page.title()
            final_url = page.url
            log.info("browser_navigate", url=url, title=title)
            return ToolResult(
                success=True,
                data={"title": title, "url": final_url},
                meta={"risk": ToolRisk.SAFE},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def get_text(self, selector: str = "body") -> ToolResult:
        """Extract visible text from CSS selector. Risk: SAFE."""
        try:
            page = await self._get_page()
            el   = await page.query_selector(selector)
            text = (await el.inner_text()) if el else ""
            return ToolResult(
                success=True,
                data={"text": text[:8000]},
                meta={"risk": ToolRisk.SAFE, "selector": selector},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def screenshot(self, path: Optional[str] = None) -> ToolResult:
        """Take screenshot; return base64 if < 200 KB. Risk: SAFE."""
        try:
            page      = await self._get_page()
            save_path = path or os.path.join(
                tempfile.gettempdir(), "bea_screenshot.png"
            )
            await page.screenshot(path=save_path, full_page=False)
            size = os.path.getsize(save_path)
            data: dict = {"path": save_path, "size_bytes": size}
            if size < 200 * 1024:
                with open(save_path, "rb") as f:
                    data["base64"] = base64.b64encode(f.read()).decode()
            log.info("browser_screenshot", path=save_path, size=size)
            return ToolResult(success=True, data=data, meta={"risk": ToolRisk.SAFE})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def click(self, selector: str) -> ToolResult:
        """Click an element. Risk: SUPERVISED."""
        try:
            page = await self._get_page()
            await page.click(selector, timeout=_TIMEOUT_MS)
            log.info("browser_click", selector=selector)
            return ToolResult(
                success=True,
                data={"selector": selector},
                meta={"risk": ToolRisk.SUPERVISED},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def fill_form(self, selector: str, value: str) -> ToolResult:
        """Fill an input field. Risk: SUPERVISED."""
        try:
            page = await self._get_page()
            await page.fill(selector, value, timeout=_TIMEOUT_MS)
            log.info("browser_fill", selector=selector)
            return ToolResult(
                success=True,
                data={"selector": selector},
                meta={"risk": ToolRisk.SUPERVISED},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def execute_js(self, script: str) -> ToolResult:
        """Run arbitrary JavaScript. Risk: DANGEROUS — requires allow_dangerous=True."""
        if not self.allow_dangerous:
            return ToolResult(
                success=False,
                error="JS execution blocked. Pass allow_dangerous=True to BrowserTool.",
            )
        try:
            page   = await self._get_page()
            result = await page.evaluate(script)
            log.warning("browser_js_exec", script_len=len(script))
            return ToolResult(
                success=True,
                data={"result": result},
                meta={"risk": ToolRisk.DANGEROUS},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def extract_links(self) -> ToolResult:
        """Return list of {text, href} from all <a> tags on current page. Risk: SAFE."""
        try:
            page  = await self._get_page()
            links = await page.evaluate(
                """
                () => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({
                        text: a.innerText.trim().substring(0, 120),
                        href: a.href
                    }))
                    .filter(l => l.href.startsWith('http'))
                    .slice(0, 100)
                """
            )
            return ToolResult(
                success=True,
                data={"links": links, "count": len(links)},
                meta={"risk": ToolRisk.SAFE},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def search_web(
        self, query: str, engine: str = "duckduckgo"
    ) -> ToolResult:
        """Navigate to search engine and extract top 10 results. Risk: SAFE."""
        _engines = {
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web",
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
        }
        url = _engines.get(engine, _engines["duckduckgo"])

        nav = await self.navigate(url)
        if not nav.success:
            return nav

        try:
            page = await self._get_page()
            await page.wait_for_timeout(1500)

            if engine == "duckduckgo":
                results = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('[data-result]'))
                        .slice(0, 10)
                        .map(r => ({
                            title:   r.querySelector('a[data-testid="result-title-a"]')?.innerText || '',
                            url:     r.querySelector('a[data-testid="result-title-a"]')?.href || '',
                            snippet: r.querySelector('[data-result="snippet"]')?.innerText || ''
                        }))
                        .filter(r => r.title)
                    """
                )
            elif engine == "google":
                results = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('.g'))
                        .slice(0, 10)
                        .map(r => ({
                            title:   r.querySelector('h3')?.innerText || '',
                            url:     r.querySelector('a')?.href || '',
                            snippet: r.querySelector('.VwiC3b')?.innerText || ''
                        }))
                        .filter(r => r.title)
                    """
                )
            else:  # bing
                results = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('.b_algo'))
                        .slice(0, 10)
                        .map(r => ({
                            title:   r.querySelector('h2')?.innerText || '',
                            url:     r.querySelector('a')?.href || '',
                            snippet: r.querySelector('.b_caption p')?.innerText || ''
                        }))
                        .filter(r => r.title)
                    """
                )

            log.info("browser_search", query=query, engine=engine, n=len(results))
            return ToolResult(
                success=True,
                data={"results": results, "count": len(results), "engine": engine},
                meta={"risk": ToolRisk.SAFE},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
