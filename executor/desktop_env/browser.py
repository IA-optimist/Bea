"""
BEA MAX v3 — Web Surfer
Ajoute les yeux sur internet à l'Agent Autonome. Mieux vaut un parser léger 
qu'un lourd navigateur Headless pour 90% des lectures de doc.
"""
import re
import structlog

try:
    import httpx as requests
except ImportError:
    requests = None

log = structlog.get_logger()

class WebSurfer:
    """Un navigateur textuel léger pour lire documentation, GitHub, StackOverflow."""

    def navigate(self, url: str) -> str:
        log.info("websurfer_navigate", url=url)
        if not requests:
            return "❌ Erreur: 'httpx' non installé. Pip install httpx."

        try:
            # Header très permissif pour éviter les bloqueurs basiques
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BeaMax-v3"
            }
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            
            html = r.text
            
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                # Supprimer les balises inutiles pour concentrer le contexte
                for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    script.extract()
                text = soup.get_text(separator='\n', strip=True)
            except ImportError:
                # Fallback brut Regex si bs4 n'est pas là
                log.warning("websurfer_bs4_missing_using_regex")
                text = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.DOTALL)
                text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^<]+>', '\n', text)
                text = re.sub(r'\n+', '\n', text).strip()
            
            # Limite de sécurité pour Context Window LLM (~ 8000 chars)
            if len(text) > 8000:
                text = text[:4000] + "\n\n... [TRONQUÉ PAR BEA] ...\n\n" + text[-4000:]
                
            return text
            
        except requests.HTTPStatusError as e:
            return f"❌ Erreur HTTP {e.response.status_code} sur {url}."
        except Exception as e:
            return f"❌ Erreur navigation vers {url}: {str(e)}"
