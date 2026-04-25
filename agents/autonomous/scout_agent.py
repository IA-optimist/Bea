"""
JARVIS MAX v3 — Scout Researcher Agent
Agent spécialisé dans la recherche documentaire parallèle.
"""
from typing import Any

import structlog
# NOTE: TokenRouter removed (deprecated). ScoutResearcher is legacy/unused.
try:
    from core.model_router import TokenRouter
except ImportError:
    TokenRouter = None  # type: ignore

log = structlog.get_logger()

class ScoutResearcher:
    """Agent léger qui utilise le WebSurfer pour trouver des infos sans bloquer le Cerveau."""
    
    def __init__(self):
        self.router = TokenRouter()

    async def research(self, query: str, browser: Any) -> str:
        """Effectue une recherche web et résume les résultats."""
        log.info("scout_research_start", query=query)
        
        # 1. Navigation (Simulée ou réelle)
        # On pourrait utiliser un moteur de recherche si implémenté, 
        # ici on va sur Google/DuckDuckGo par défaut via le WebSurfer
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        raw_html = browser.navigate(search_url)
        
        if "❌" in raw_html:
            return f"Échec de la recherche web pour : {query}"

        # 2. Résumé par LLM (modèle léger pour économiser)
        prompt = f"""
        Tu es un Agent Scout. Voici le contenu brut d'une recherche pour la question : '{query}'
        Résume les points clés techniquement pour aider un développeur principal.
        
        CONTENU :
        {raw_html[:4000]}
        
        RÉSUMÉ :
        """
        
        # Utilise un modèle rapide (Haiku / Mini)
        summary = await self.router.completion(
            prompt=prompt,
            role="scout",
            model_hint="fast" 
        )
        
        return summary
