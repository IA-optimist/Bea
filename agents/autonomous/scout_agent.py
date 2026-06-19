"""
BEA MAX v3 - Scout Researcher Agent
Agent spécialisé dans la recherche documentaire parallèle.
"""
from __future__ import annotations

from typing import Any, cast

import structlog

# NOTE: TokenRouter removed (deprecated). ScoutResearcher is legacy/unused.
try:
    from core.model_router import TokenRouter
except ImportError:
    TokenRouter = None

log = structlog.get_logger()


class ScoutResearcher:
    """Agent léger qui utilise le WebSurfer pour trouver des infos sans bloquer le Cerveau."""

    def __init__(self) -> None:
        if TokenRouter is None:
            raise RuntimeError("TokenRouter unavailable")
        self.router: Any = TokenRouter()

    async def research(self, query: str, browser: Any) -> str:
        """Effectue une recherche web et résume les résultats."""
        log.info("scout_research_start", query=query)

        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        raw_html = browser.navigate(search_url)

        if "❌" in raw_html:
            return f"Échec de la recherche web pour : {query}"

        prompt = f"""
        Tu es un Agent Scout. Voici le contenu brut d'une recherche pour la question : '{query}'
        Résume les points clés techniquement pour aider un développeur principal.

        CONTENU :
        {raw_html[:4000]}

        RÉSUMÉ :
        """

        summary = await self.router.completion(
            prompt=prompt,
            role="scout",
            model_hint="fast",
        )

        return cast(str, summary)
