"""
BEA MAX — WebScoutResearch Agent
Agent de recherche web réel via Playwright (tools/browser/scraper.py).

Complète ScoutResearch (LLM-only) en ajoutant un accès web réel :
    1. Recherche DuckDuckGo : top N résultats
    2. Scraping contenu des pages résultats (top 3)
    3. Synthèse LLM sur le contenu brut récupéré

Fallback transparent si Playwright n'est pas installé :
    → Retourne une synthèse LLM classique avec note "[WEB_UNAVAILABLE]"

Intégration :
    Déclaré dans agents/registry.py sous la clé "web-scout"
    Utilisable par AtlasDirector dans le plan d'agents

Paramètres de session exploités :
    session.user_input        : requête de base (si pas de tâche dans le plan)
    session.mission_summary   : contexte de mission
    session.get_output(...)   : contexte des agents précédents

Exemple de résultat dans session.context :
    "web-scout": "## Résultats web\n**DuckDuckGo** (3 résultats)\n..."
"""
from __future__ import annotations

import asyncio
import time
import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from agents.crew import BaseAgent
from core.state import BeaSession

log = structlog.get_logger()

_MAX_SEARCH_RESULTS   = 5    # résultats DuckDuckGo à récupérer
_MAX_PAGE_CHARS       = 2000  # caractères max par page scrapée
_MAX_PAGES_TO_SCRAPE  = 3     # nombre de pages à scraper en détail
_SYNTHESIS_MAX_INPUT  = 8000  # caractères max injectés dans le prompt LLM


class WebScoutResearch(BaseAgent):
    """
    Agent de recherche web réel.

    Flux d'exécution :
        1. search_and_scrape(query) → top N résultats DuckDuckGo
        2. get_text(url) sur top 3 URLs → contenu brut
        3. LLM synthesis → rapport structuré injecté dans session

    Timeout global : 90s (recherche + scraping + LLM)
    """
    name      = "web-scout"
    role      = "research"
    timeout_s = 90

    def system_prompt(self) -> str:
        return (
            "Tu es WebScoutResearch, agent de recherche web de BeaMax.\n"
            "Tu analyses du contenu web réel extrait par navigation Playwright.\n"
            "Tu identifies les faits clés, tendances, acteurs, chiffres importants.\n"
            "Tu synthétises de façon structurée avec des sections claires.\n"
            "Indique toujours les URLs sources de chaque information.\n"
            "Si le contenu est insuffisant, dis-le explicitement.\n"
            "Lecture seule — tu ne génères pas d'actions."
        )

    def user_message(self, session: BeaSession) -> str:
        # Appel standard (sans contenu web) — utilisé uniquement en fallback
        task = self._task(session)
        return (
            f"Mission : {session.mission_summary}\n"
            f"Tâche : {task}\n\n"
            "[FALLBACK — navigation web indisponible]\n"
            "Analyse et synthétise avec ta connaissance interne."
        )

    def _build_web_user_message(
        self,
        session: BeaSession,
        search_results: list[dict],
        page_contents: list[dict],
    ) -> str:
        task = self._task(session)

        # Section résultats de recherche
        sr_lines = [f"## Résultats DuckDuckGo ({len(search_results)} trouvés)"]
        for i, r in enumerate(search_results, 1):
            sr_lines.append(
                f"[{i}] {r.get('title', '?')}\n"
                f"    URL : {r.get('url', '?')}\n"
                f"    Extrait : {r.get('snippet', '')[:200]}"
            )

        # Section contenu des pages
        pc_lines = ["\n## Contenu des pages visitées"]
        for pc in page_contents:
            pc_lines.append(
                f"\n### {pc['url']}\n"
                f"{pc['content'][:_MAX_PAGE_CHARS]}"
            )

        web_block = "\n".join(sr_lines + pc_lines)
        # Tronquer si trop long
        if len(web_block) > _SYNTHESIS_MAX_INPUT:
            web_block = web_block[:_SYNTHESIS_MAX_INPUT] + "\n...[tronqué]"

        ctx = self._ctx(session)
        ctx_section = f"\n\nContexte agents précédents :\n{ctx}" if ctx else ""

        return (
            f"Mission : {session.mission_summary}\n"
            f"Tâche : {task}\n\n"
            f"{web_block}"
            f"{ctx_section}\n\n"
            f"Synthétise les informations web ci-dessus en rapport structuré."
        )

    # ── run() override ────────────────────────────────────────

    async def run(self, session: BeaSession) -> str:
        t0 = time.monotonic()
        log.info("web_scout_start", mission_id=session.session_id)

        query = self._task(session) or session.user_input

        try:
            result = await asyncio.wait_for(
                self._run_with_browser(session, query),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning("web_scout_timeout", mission_id=session.session_id)
            result = await self._run_fallback(session, note="[TIMEOUT web scraping]")
        except Exception as e:
            log.error("web_scout_error", err=str(e), sid=session.session_id)
            result = await self._run_fallback(session, note=f"[ERREUR: {str(e)[:80]}]")

        ms = int((time.monotonic() - t0) * 1000)
        session.set_output(self.name, result, success=bool(result), ms=ms)
        log.info("web_scout_done", ms=ms, chars=len(result))
        return result

    async def _run_with_browser(self, session: BeaSession, query: str) -> str:
        """Flux principal : browser → LLM synthesis."""
        from tools.browser.scraper import BrowserTool

        search_results: list[dict] = []
        page_contents: list[dict] = []

        async with BrowserTool(self.s) as browser:
            # Étape 1 : recherche
            try:
                search_results = await browser.search_and_scrape(
                    query, engine="duckduckgo"
                )
                search_results = search_results[:_MAX_SEARCH_RESULTS]
                log.info("web_scout_search_done",
                         query=query[:60], results=len(search_results))
            except Exception as e:
                log.warning("web_scout_search_failed", err=str(e))

            # Étape 2 : scraping des top pages
            urls_to_scrape = [
                r["url"] for r in search_results
                if r.get("url", "").startswith("http")
            ][:_MAX_PAGES_TO_SCRAPE]

            for url in urls_to_scrape:
                try:
                    content = await asyncio.wait_for(
                        browser.get_text(url),
                        timeout=15,
                    )
                    if content and len(content.strip()) > 100:
                        page_contents.append({
                            "url":     url,
                            "content": content,
                        })
                        log.debug("web_scout_page_scraped",
                                  url=url[:60], chars=len(content))
                except Exception as e:
                    log.warning("web_scout_page_failed", url=url[:60], err=str(e))

        if not search_results and not page_contents:
            return await self._run_fallback(session, note="[AUCUN RÉSULTAT WEB]")

        # Étape 3 : synthèse LLM (via safe_invoke — circuit breaker + fallback)
        user_msg = self._build_web_user_message(session, search_results, page_contents)
        try:
            from core.llm_factory import LLMFactory
            factory = LLMFactory(self.s)
            resp = await factory.safe_invoke(
                [
                    SystemMessage(content=self.system_prompt()),
                    HumanMessage(content=user_msg),
                ],
                role=self.role,
                timeout=60.0,
            )
            return resp.content if resp else self._format_raw_results(search_results, page_contents)
        except asyncio.TimeoutError:
            # Retourner le contenu brut sans synthèse LLM
            return self._format_raw_results(search_results, page_contents)

    async def _run_fallback(self, session: BeaSession, note: str = "") -> str:
        """Fallback LLM classique si Playwright indisponible ou timeout."""
        try:
            from core.llm_factory import LLMFactory
            factory = LLMFactory(self.s)
            msg = self.user_message(session)
            if note:
                msg = f"{note}\n\n{msg}"
            resp = await factory.safe_invoke(
                [
                    SystemMessage(content=self.system_prompt()),
                    HumanMessage(content=msg),
                ],
                role=self.role,
                timeout=45.0,
            )
            return f"[WEB_UNAVAILABLE] {resp.content if resp else '(pas de réponse)'}"
        except Exception as e:
            log.error("web_scout_fallback_failed", err=str(e))
            return f"[WEB_SCOUT_ERROR] {note} {str(e)[:150]}"

    @staticmethod
    def _format_raw_results(
        search_results: list[dict],
        page_contents: list[dict],
    ) -> str:
        """Formate les résultats bruts sans synthèse LLM."""
        lines = ["## Résultats web (synthèse LLM indisponible)\n"]
        for r in search_results:
            lines.append(
                f"- **{r.get('title', '?')}**\n"
                f"  {r.get('url', '')}\n"
                f"  {r.get('snippet', '')[:200]}"
            )
        if page_contents:
            lines.append("\n## Contenus extraits")
            for pc in page_contents:
                lines.append(
                    f"\n### {pc['url']}\n"
                    f"{pc['content'][:1000]}"
                )
        return "\n".join(lines)
