"""Pilote Béa depuis Telegram (dev/test, long-polling).

Permet de tester le modèle (bea-v31) et l'agent (orchestration) sans l'APK.

Pré-requis :
  - `bea-v31` servi dans Ollama (Phase E) pour /chat et /mission
  - variables d'env (depuis .env) : TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS,
    OLLAMA_HOST, OLLAMA_MODEL_MAIN, CODEX_BASE_URL...

Lancement (venv local) :
    set -a; source .env; set +a
    python scripts/run_telegram_bea.py

Commandes Telegram :
    /chat <texte>    -> réponse directe de bea-v31 (1 tour, rapide)
    /mission <texte> -> mission complète (Codex director + bea-v31 workers)
    /whoami          -> affiche ton user_id Telegram
    /start, /help    -> aide
    (texte simple)   -> traité comme /chat
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

# Permet `python scripts/run_telegram_bea.py` depuis la racine du repo
# (sinon `scripts/` est sur le path, pas la racine, et `import config` échoue).
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Console/logs en UTF-8 : structlog crashe sinon sur les accents (cp1252 Windows).
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from config.settings import get_settings
from core.llm_factory import LLMFactory
from gateway.adapters.telegram import TelegramAdapter
from gateway.base import MessageEvent
from gateway.runner import GatewayRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telegram_bea")


def _load_dotenv() -> None:
    """Charge .env à la racine du repo dans os.environ (sans écraser l'existant).

    Béa lit os.environ directement (pas de load_dotenv global) ; ce script de test
    se rend auto-suffisant pour un lancement simple en venv local.
    """
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        # .env = config du bot : on ÉCRASE l'env global (ex: OLLAMA_HOST=0.0.0.0
        # = adresse d'écoute serveur, invalide comme cible de connexion client).
        if key:
            os.environ[key] = val


def _allowlist() -> set[str] | None:
    raw = os.getenv("TELEGRAM_ALLOWED_USERS", "").strip()
    ids = {u.strip() for u in raw.split(",") if u.strip()}
    return ids or None  # None => tout autorisé (déconseillé)


import re as _re

from gateway.local_tools import TOOLS_DOC, parse_tool_call, run_tool

# System prompt : Béa a de VRAIS outils exécutables (boucle tool_call -> tool_result).
TOOLS_AGENT = (
    "Tu es Béa, assistante IA francophone experte. Tu disposes d'OUTILS RÉELS exécutés sur la "
    "machine WINDOWS de l'utilisateur :\n" + TOOLS_DOC + "\n\nRÈGLES STRICTES :\n"
    "1. Pour toute demande nécessitant une info système, émets DIRECTEMENT le bon <tool_call> "
    "SANS demander de confirmation — les lectures sont sûres et l'utilisateur attend le résultat.\n"
    "2. Commandes Windows utiles : config réseau = `ipconfig /all` ; hôtes du réseau = `arp -a` ; "
    "contenu d'un dossier = `dir \"<chemin>\"` ; processus = `tasklist` ; test ping = `ping <ip>`.\n"
    "3. Demande confirmation UNIQUEMENT avant une action qui MODIFIE ou SUPPRIME (write_file, "
    "suppression de fichier). Jamais pour une simple lecture/diagnostic.\n"
    "4. Émets UN SEUL <tool_call>{\"tool\":\"...\",\"arguments\":{...}}</tool_call>. Le résultat RÉEL "
    "revient en <tool_result> ; réponds ENSUITE à partir de ce résultat, sans rien inventer.\n"
    "5. N'invente jamais d'outil hors de la liste, ni de résultat, ni de fichier.\n"
    "6. Pour une question sur les NOTES/connaissances/projets de l'utilisateur (faits précis, "
    "préférences, contenu personnel), commence par knowledge_search{query}. Réponds À PARTIR "
    "des extraits sourcés et CITE la source. Si le résultat est AUCUN_RESULTAT ou hors-sujet, "
    "dis clairement que l'information n'est pas dans la base — n'invente pas.\n"
    "Réponds en français, concise."
)


# Intention explicite « mes notes/documents » -> force le RAG (le LLM oublie parfois l'outil).
_NOTES_HINT = _re.compile(
    r"\b(?:mes|mon|ma)\s+(?:notes?|documents?|docs?|fiches?|projets?)\b|"
    r"d['’]apr[eè]s mes|selon mes|dans mes notes|ma base de connaissance",
    _re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Retire le raisonnement interne (<analysis>/<think>) de la réponse affichée."""
    text = _re.sub(r"<analysis>.*?</analysis>", "", text or "", flags=_re.DOTALL)
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL)
    return text.strip()


def _build_handler(settings):
    from collections import deque

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    factory = LLMFactory(settings)
    history: dict[str, deque] = {}          # chat_id -> derniers tours (mémoire court terme)

    try:                                     # mémoire hybride (best-effort, fallback gracieux)
        from memory.memory_bus import MemoryBus
        bus = MemoryBus(settings)
    except Exception:                        # noqa: BLE001
        bus = None

    # ── Cerveau agent : gpt-oss-120b -> nemotron-120b (OpenRouter) -> bea-v31 local ──
    # Codex-gateway écarté par défaut : il boucle sur les outils (= agent Hermes complet,
    # pas du Codex brut) + traîne ~108k tokens de contexte. Réactivable via AGENT_PRIMARY=codex.
    from langchain_openai import ChatOpenAI
    _or_key = os.getenv("OPENROUTER_API_KEY", "")

    def _or_model(mid: str):
        return ChatOpenAI(model=mid, base_url="https://openrouter.ai/api/v1",
                          api_key=_or_key, temperature=0.3, timeout=90, max_retries=3)

    _chain = []
    if os.getenv("AGENT_PRIMARY", "openrouter") == "codex":
        _chain.append(ChatOpenAI(model=getattr(settings, "codex_model", "hermes-agent"),
                                 base_url=getattr(settings, "codex_base_url",
                                                  "http://127.0.0.1:8642/v1"),
                                 api_key=getattr(settings, "codex_api_key", "none") or "none",
                                 temperature=0.3, timeout=90))
    if _or_key:
        _chain.append(_or_model(os.getenv("AGENT_OR_MODEL", "openai/gpt-oss-120b:free")))
        _chain.append(_or_model(os.getenv("AGENT_OR_FALLBACK",
                                          "nvidia/nemotron-3-super-120b-a12b:free")))

    async def _agent_invoke(msgs):
        """Essaie les cerveaux dans l'ordre ; bea-v31 (factory) en dernier recours."""
        for m in _chain:
            try:
                r = await m.ainvoke(msgs)
                if (getattr(r, "content", "") or "").strip():
                    return r
            except Exception as e:           # noqa: BLE001
                log.warning("agent_brain_failed: %s", str(e)[:160])
        return await factory.get("default").ainvoke(msgs)  # fallback local bea-v31

    # Routage HYBRIDE : question conversationnelle (sans outil) -> AGENT COMPLET (cognition).
    _api_url = os.getenv("BEA_API_URL", "http://127.0.0.1:8000").rstrip("/")
    _api_token = os.getenv("JARVIS_API_TOKEN", "localdev")
    _use_cognition = os.getenv("BEA_USE_COGNITION", "1") not in ("0", "false", "no", "")

    async def _cognition_via_api(message: str, hist) -> dict | None:
        """POST /api/v3/chat (cognition complète). Renvoie {response, confidence,
        reasoning} ou None si l'API est indisponible (-> repli local)."""
        if not _use_cognition:
            return None
        payload = {
            "message": message,
            "conversation_history": [{"role": r, "content": c} for r, c in list(hist)[-6:]],
            "enable_self_correction": True,
        }
        try:
            async with httpx.AsyncClient(timeout=75) as c:
                resp = await c.post(f"{_api_url}/api/v3/chat", json=payload,
                                    headers={"X-Jarvis-Token": _api_token})
            if resp.status_code == 200:
                d = resp.json()
                txt = (d.get("response") or "").strip()
                if txt:
                    return {"response": txt,
                            "confidence": d.get("confidence_score"),
                            "reasoning": d.get("reasoning_used")}
        except Exception as e:               # noqa: BLE001
            log.info("cognition_api_unavailable (-> local): %s", str(e)[:120])
        return None

    async def _chat(chat_id: str, msg: str) -> str:
        # 1. Rappel mémoire hybride (best-effort)
        ctx = ""
        if bus is not None:
            try:
                mems = await bus.recall(msg, top_k=3)
                if mems:
                    ctx = "\n\nÉléments mémorisés pertinents :\n" + "\n".join(
                        f"- {m.get('text', '')[:200]}" for m in mems[:3])
            except Exception:                # noqa: BLE001
                pass
        # 2. Messages : system (avec outils réels) + historique + message courant
        h = history.setdefault(chat_id, deque(maxlen=12))
        msgs = [SystemMessage(content=TOOLS_AGENT + ctx)]
        for role, content in h:
            msgs.append(HumanMessage(content=content) if role == "user"
                        else AIMessage(content=content))
        msgs.append(HumanMessage(content=msg))
        # 3. Boucle agentique : tool_call -> exécution RÉELLE -> tool_result -> réponse
        tools_run: list[str] = []
        seen: set[str] = set()               # garde anti-boucle (même outil ré-émis)
        answer = ""
        last_result = ""                     # dernière sortie d'outil (fallback si pas de formulation)
        for _ in range(4):
            resp = await _agent_invoke(msgs)
            answer = getattr(resp, "content", None) or str(resp)
            tc = parse_tool_call(answer)
            if tc is None:
                break
            sig = str(tc)
            if sig in seen:                  # déjà exécuté -> on formulera la réponse finale
                break
            seen.add(sig)
            result = await asyncio.to_thread(run_tool, tc)   # exécution hors event-loop
            last_result = result
            tools_run.append(f"🔧 {tc['tool']}")
            log.info("tool_executed %s -> %s", tc["tool"], result[:120].replace("\n", " "))
            msgs.append(AIMessage(content=answer))
            msgs.append(HumanMessage(content=(
                f"<tool_result>{result}</tool_result>\nRéponds maintenant à l'utilisateur "
                "EN FRANÇAIS à partir de ce résultat. Ne ré-émets PAS de tool_call sauf si une "
                "autre action est réellement nécessaire.")))
        # Si la dernière sortie est encore un tool_call (modèle qui boucle), force une formulation.
        if tools_run and parse_tool_call(answer) is not None:
            msgs.append(HumanMessage(content="Formule ta réponse finale en français à partir des "
                                             "résultats obtenus. N'inclus AUCUN tool_call."))
            try:
                resp = await _agent_invoke(msgs)
                answer = getattr(resp, "content", None) or answer
            except Exception:                # noqa: BLE001
                pass
        # Routage HYBRIDE quand aucun outil n'a été utilisé :
        #  - intention explicite « mes notes » -> on FORCE le RAG (le LLM oublie parfois) ;
        #  - sinon question de raisonnement/conseil -> AGENT COMPLET (cognition).
        cognition_used = False
        if not tools_run and _NOTES_HINT.search(msg):
            kres = await asyncio.to_thread(
                run_tool, {"tool": "knowledge_search", "arguments": {"query": msg}})
            tools_run.append("🔧 knowledge_search")
            last_result = kres
            if "AUCUN_RESULTAT" in kres:
                answer = "Je n'ai rien trouvé là-dessus dans tes notes."
            else:
                msgs.append(HumanMessage(content=(
                    f"<tool_result>{kres}</tool_result>\nRéponds en français à partir de ces "
                    "extraits et cite la source.")))
                try:
                    resp = await _agent_invoke(msgs)
                    answer = getattr(resp, "content", None) or answer
                except Exception:            # noqa: BLE001
                    answer = kres[:1500]
        elif not tools_run:
            cog = await _cognition_via_api(msg, h)
            if cog:
                answer = cog["response"]
                cognition_used = True
                log.info("cognition_used conf=%s reasoning=%s",
                         cog.get("confidence"), cog.get("reasoning"))
        # Nettoyage : retire tout artefact d'appel d'outil OÙ QU'IL SOIT (balises, raccourci
        # <nom{…}>, et blob d'arguments JSON {"query":…}/{"command":…} laissé en clair).
        final = _clean(answer)
        final = _re.sub(r"</?tool_call>", "", final)
        final = _re.sub(r"<[a-zA-Z_]\w*(?=\s*\{)", "", final)         # préfixe <nom devant un {
        final = _re.sub(
            r'\{\s*"(tool|query|q|question|arguments|command|code|path)"\s*:.*?\}\s*>?',
            "", final, flags=_re.DOTALL)                              # blob d'arguments d'outil
        final = _re.sub(r"^(?:🔧\s*\w+\s*)+", "", final).strip()     # écho éventuel du préfixe outil
        if not final and tools_run:          # modèle qui n'a pas formulé -> repli déterministe
            if "AUCUN_RESULTAT" in last_result:
                final = "Je n'ai rien trouvé de pertinent dans tes notes là-dessus."
            else:
                final = last_result.strip()[:1500] or "(résultats obtenus)"
        elif not final:
            final = "(pas de réponse)"
        if tools_run:
            final = " ".join(dict.fromkeys(tools_run)) + "\n" + final
        elif cognition_used:
            final = "🧠 " + final          # réponse de l'agent complet (cognition)
        # 4. Mémoire court terme + hybride
        h.append(("user", msg))
        h.append(("assistant", final))
        if bus is not None:
            try:
                bus.remember(f"User: {msg}\nBéa: {final}",
                             metadata={"chat_id": str(chat_id), "type": "conversation"},
                             tags=["conversation"])
            except Exception:                # noqa: BLE001
                pass
        return final

    async def handler(event: MessageEvent) -> str:
        text = event.text.strip()

        # Utilitaires uniquement — sinon TOUT message parle directement à Béa.
        if text.startswith("/whoami"):
            return f"Ton user_id Telegram : {event.user_id}"
        if text.startswith(("/start", "/help")):
            return ("Béa en ligne \U0001f7e2\n"
                    "Parle-moi directement — je me souviens du fil de la conversation.\n"
                    "/reset — repartir de zéro · /whoami — ton id")
        if text.startswith("/reset"):
            history.pop(event.chat_id, None)
            return "Fil de conversation effacé. 🧹"

        # Tout le reste -> Béa (mémoire de conversation + mémoire hybride).
        if not text:
            return "Dis-moi quelque chose 🙂"
        try:
            return await _chat(event.chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.exception("chat_failed")
            return f"Erreur : {e}"

    return handler


async def main() -> None:
    _load_dotenv()  # avant get_settings() : settings lit os.environ
    # Single-instance : tue l'instance précédente du bot (fin des orphelins en conflit).
    pidfile = Path(__file__).resolve().parent / ".bea_bot.pid"
    if pidfile.exists():
        old = pidfile.read_text(encoding="utf-8").strip()
        if old.isdigit() and old != str(os.getpid()):
            os.system(f"taskkill /F /PID {old} >nul 2>&1")  # noqa: S605
    pidfile.write_text(str(os.getpid()), encoding="utf-8")
    settings = get_settings()
    adapter = TelegramAdapter()
    if not adapter.token:
        raise SystemExit("TELEGRAM_BOT_TOKEN manquant — exporte le .env d'abord.")

    runner = GatewayRunner(handler=_build_handler(settings), allowlist=_allowlist())
    runner.register(adapter)
    log.info("Bot Telegram démarré (allowlist=%s). Ctrl-C pour arrêter.", _allowlist())

    offset = 0
    async with httpx.AsyncClient(timeout=40) as client:
        while True:
            try:
                r = await client.get(f"{adapter.base_url}/getUpdates",
                                     params={"offset": offset, "timeout": 30})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    event = adapter.parse(upd)
                    if event:
                        log.info("msg from %s: %s", event.user_id, event.text[:80])
                        await runner.dispatch(event)
            except Exception as e:  # noqa: BLE001
                log.warning("poll_error: %s", e)
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
