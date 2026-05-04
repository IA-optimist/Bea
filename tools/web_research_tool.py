"""
WebResearchTool — DuckDuckGo HTML scraper + HTTP fetch.
No API key required. Fail-open on network errors.
"""
from __future__ import annotations

import re

from tools.base import BaseTool, ToolRisk

_OFFLINE = {"success": False, "error": "offline", "results": []}


class WebResearchTool(BaseTool):
    name = "web_research_tool"
    risk = ToolRisk.SAFE

    def search(self, query: str, max_results: int = 5) -> dict:
        """Search DuckDuckGo HTML (no API key). Returns list of {title, url, snippet}."""
        try:
            import urllib.parse
            import urllib.request

            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisMax/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Parse results from DDG HTML
            results = []
            # Match result blocks
            pattern = re.compile(
                r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                re.DOTALL,
            )
            for m in pattern.finditer(html):
                href, title, snippet = m.group(1), m.group(2), m.group(3)
                title = re.sub(r"<[^>]+>", "", title).strip()
                snippet = re.sub(r"<[^>]+>", "", snippet).strip()
                if href and title:
                    results.append({"title": title, "url": href, "snippet": snippet})
                if len(results) >= max_results:
                    break

            return {"success": True, "results": results, "query": query}
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("timeout", "connect", "network", "resolve")):
                return _OFFLINE
            return {"success": False, "error": err, "results": []}

    def fetch(self, url: str, timeout: int = 10) -> dict:
        """Fetch URL content. Returns text content."""
        try:
            import urllib.request

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisMax/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                # Strip HTML tags for cleaner output
                text = re.sub(r"<[^>]+>", "", content)
                text = re.sub(r"\s+", " ", text).strip()
                return {"success": True, "content": text[:10000], "url": url}
        except Exception as e:
            err = str(e)
            if any(x in err.lower() for x in ("timeout", "connect", "network", "resolve")):
                return _OFFLINE
            return {"success": False, "error": err, "content": ""}
