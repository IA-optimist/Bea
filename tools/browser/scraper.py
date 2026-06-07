"""
BEA MAX — Browser Automation (Playwright)
Capacités : navigation, scraping, formulaires, screenshots.
"""
from __future__ import annotations
import asyncio
import structlog
from pathlib import Path

log = structlog.get_logger()


class BrowserTool:

    def __init__(self, settings=None):
        self.headless = getattr(settings, "browser_headless", True) if settings else True
        self.timeout  = getattr(settings, "browser_timeout", 30000) if settings else 30000
        self._browser = None
        self._context = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self):
        try:
            from playwright.async_api import async_playwright
            self._pw      = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            log.info("browser_started", headless=self.headless)
        except ImportError:
            log.error("playwright_not_installed")
            raise RuntimeError(
                "Playwright non installé. Exécute : pip install playwright && playwright install chromium"
            )

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw"):
            await self._pw.stop()
        log.info("browser_stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()

    # ── Navigation ────────────────────────────────────────────

    async def open_page(self, url: str) -> str:
        """Ouvre une URL et retourne le titre de la page."""
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            title = await page.title()
            log.info("browser_page_opened", url=url, title=title)
            return title
        finally:
            await page.close()

    async def get_text(self, url: str, selector: str | None = None) -> str:
        """Récupère le texte d'une page ou d'un sélecteur CSS."""
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            await asyncio.sleep(1)  # Laisser JS charger
            if selector:
                el   = await page.query_selector(selector)
                text = await el.inner_text() if el else "(sélecteur introuvable)"
            else:
                text = await page.inner_text("body")
            return text[:5000]   # Limiter la taille
        finally:
            await page.close()

    async def scrape_links(self, url: str) -> list[dict]:
        """Extrait tous les liens d'une page."""
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            links = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    text: a.innerText.trim().substring(0, 100),
                    href: a.href
                })).filter(l => l.href.startsWith('http')).slice(0, 50)
            """)
            return links
        finally:
            await page.close()

    async def screenshot(self, url: str, output_path: str) -> str:
        """Prend un screenshot d'une page."""
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=output_path, full_page=True)
            log.info("screenshot_saved", path=output_path)
            return output_path
        finally:
            await page.close()

    async def fill_form(self, url: str, fields: dict[str, str], submit_selector: str | None = None) -> str:
        """
        Remplit un formulaire.
        fields = {"#username": "value", "#password": "secret"}
        """
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            for selector, value in fields.items():
                el = await page.query_selector(selector)
                if el:
                    await el.fill(value)
                else:
                    log.warning("form_field_not_found", selector=selector)

            if submit_selector:
                btn = await page.query_selector(submit_selector)
                if btn:
                    await btn.click()
                    await page.wait_for_load_state("networkidle", timeout=self.timeout)

            return await page.title()
        finally:
            await page.close()

    async def search_and_scrape(self, query: str, engine: str = "duckduckgo") -> list[dict]:
        """Effectue une recherche et retourne les résultats."""
        urls = {
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web",
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
        }
        url  = urls.get(engine, urls["duckduckgo"])
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            await asyncio.sleep(2)

            if engine == "duckduckgo":
                results = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('[data-result]')).slice(0, 10).map(r => ({
                        title: r.querySelector('a[data-testid="result-title-a"]')?.innerText || '',
                        url:   r.querySelector('a[data-testid="result-title-a"]')?.href || '',
                        snippet: r.querySelector('[data-result="snippet"]')?.innerText || ''
                    })).filter(r => r.title)
                """)
            else:
                results = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('.g')).slice(0, 10).map(r => ({
                        title: r.querySelector('h3')?.innerText || '',
                        url:   r.querySelector('a')?.href || '',
                        snippet: r.querySelector('.VwiC3b')?.innerText || ''
                    })).filter(r => r.title)
                """)

            return results
        finally:
            await page.close()

    async def extract_structured(self, url: str, schema: dict) -> dict:
        """
        Extrait des données structurées selon un schéma de sélecteurs CSS.
        schema = {"title": "h1", "price": ".price", "description": "#desc"}
        """
        page = await self._context.new_page()
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            result = {}
            for key, selector in schema.items():
                el = await page.query_selector(selector)
                result[key] = await el.inner_text() if el else None
            return result
        finally:
            await page.close()
