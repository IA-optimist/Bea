"""
BEA MAX v3 - Web Surfer
Ajoute les yeux sur internet a l'Agent Autonome. Mieux vaut un parser leger
qu'un lourd navigateur Headless pour 90% des lectures de doc.
"""
import re
from typing import cast

import structlog

try:
    import httpx
except ImportError:
    httpx = None

log = structlog.get_logger()


class WebSurfer:
    """Un navigateur textuel leger pour lire documentation, GitHub, StackOverflow."""

    def navigate(self, url: str) -> str:
        log.info("websurfer_navigate", url=url)
        client = httpx
        if client is None:
            return "Erreur: 'httpx' non installe. Pip install httpx."

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BeaMax-v3"
            }
            r = client.get(url, headers=headers, timeout=15, follow_redirects=True)
            r.raise_for_status()

            html = cast(str, r.text)

            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html, "html.parser")
                for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    script.extract()
                text = soup.get_text(separator="\n", strip=True)
            except ImportError:
                log.warning("websurfer_bs4_missing_using_regex")
                text = re.sub(r"<style.*?>.*?</style>", "", html, flags=re.DOTALL)
                text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^<]+>", "\n", text)
                text = re.sub(r"\n+", "\n", text).strip()

            if len(text) > 8000:
                text = text[:4000] + "\n\n... [TRUNCATED BY BEA] ...\n\n" + text[-4000:]

            return cast(str, text)

        except client.HTTPStatusError as e:
            return f"Erreur HTTP {e.response.status_code} sur {url}."
        except Exception as e:
            return f"Erreur navigation vers {url}: {str(e)}"
