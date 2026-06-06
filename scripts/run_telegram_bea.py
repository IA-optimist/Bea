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
    "3. Quand l'utilisateur te demande une tâche (coder, créer un fichier, éditer), FAIS-LA "
    "directement (write_file/edit_file/execute_*) sans demander de permission. Demande "
    "confirmation UNIQUEMENT avant de SUPPRIMER des fichiers ou une commande système risquée.\n"
    "4. Émets UN SEUL <tool_call>{\"tool\":\"...\",\"arguments\":{...}}</tool_call>. Le résultat RÉEL "
    "revient en <tool_result> ; réponds ENSUITE à partir de ce résultat, sans rien inventer.\n"
    "5. N'invente jamais d'outil hors de la liste, ni de résultat, ni de fichier.\n"
    "6. Pour une question sur les NOTES/connaissances/projets de l'utilisateur (faits précis, "
    "préférences, contenu personnel), commence par knowledge_search{query}. Réponds À PARTIR "
    "des extraits sourcés et CITE la source. Si le résultat est AUCUN_RESULTAT ou hors-sujet, "
    "dis clairement que l'information n'est pas dans la base — n'invente pas.\n"
    "7. Pour une info ACTUELLE, EXTERNE ou que tu ne connais pas avec certitude (actualités, "
    "prix, specs, événements récents, doc technique), utilise web_search{query} puis si besoin "
    "web_fetch{url}. Réponds à partir des résultats et cite l'URL. Ne devine pas les faits récents.\n"
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
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    factory = LLMFactory(settings)
    # Liste (pas deque) pour pouvoir replier les vieux tours en synthèse (consolidator)
    # au lieu de les jeter — mémoire de conversation bornée mais sans perte sèche.
    history: dict[str, list] = {}           # chat_id -> derniers tours (mémoire court terme)

    try:                                     # mémoire hybride (best-effort, fallback gracieux)
        from memory.memory_bus import MemoryBus
        bus = MemoryBus(settings)
    except Exception:                        # noqa: BLE001
        bus = None

    # ── Cerveau agent : Codex gpt-5.5 (abonnement ChatGPT) -> gpt-oss-120b -> nemotron -> bea-v31 ──
    # On tape le backend Codex DIRECTEMENT (gateway/codex_provider), PAS la gateway Hermes :
    # celle-ci n'expose que l'agent `hermes-agent` complet (harness 108k + boucle d'outils) qui
    # bouclait. CodexChat = Responses brut + system prompt de Béa. Désactivable: AGENT_PRIMARY=openrouter.
    from langchain_openai import ChatOpenAI
    _or_key = os.getenv("OPENROUTER_API_KEY", "")

    def _or_model(mid: str):
        return ChatOpenAI(model=mid, base_url="https://openrouter.ai/api/v1",
                          api_key=_or_key, temperature=0.3, timeout=90, max_retries=3)

    _chain = []
    if os.getenv("AGENT_PRIMARY", "codex") == "codex":
        try:
            from gateway.codex_provider import CodexChat
            _chain.append(CodexChat(model=os.getenv("CODEX_MODEL", "gpt-5.5")))
            log.info("cerveau primaire: Codex %s (abonnement ChatGPT Plus)",
                     os.getenv("CODEX_MODEL", "gpt-5.5"))
        except Exception as e:               # noqa: BLE001
            log.warning("codex_provider indisponible (-> openrouter): %s", str(e)[:160])
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
        # L'orchestrateur de cognition n'utilise que `goal` (=message) et IGNORE le champ
        # `conversation_history` -> on EMBARQUE le fil récent dans le message, sinon chaque
        # message repart de zéro (= "nouvelle discussion" à chaque message côté Telegram).
        turns = list(hist)[-6:]
        if turns:
            ctx = "\n".join(
                f"{'Béa' if r == 'assistant' else 'Utilisateur'}: {c}" for r, c in turns)
            full = ("Historique récent de NOTRE conversation (contexte — n'y réponds pas "
                    f"directement) :\n{ctx}\n\nNouveau message de l'utilisateur : {message}")
        else:
            full = message
        payload = {
            "message": full,
            "conversation_history": [{"role": r, "content": c} for r, c in turns],
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
        # 0. Vidéo YouTube -> analyse COMPLÈTE (transcription intégrale + visuel) -> cognition
        from gateway.youtube_analyzer import analyze_youtube, extract_video_id
        if extract_video_id(msg):
            res = await analyze_youtube(msg)
            if not res.get("ok"):
                return f"Je n'ai pas pu analyser cette vidéo : {res.get('error', 'inconnu')}"
            q = _re.sub(r"https?://\S+", "", msg).strip() or "Analyse cette vidéo en détail."
            ctx_yt = (f"Vidéo YouTube « {res['title']} » ({res.get('duration')}s).\n\n"
                      f"TRANSCRIPTION INTÉGRALE :\n{res['transcript']}\n\n"
                      f"OBSERVATIONS VISUELLES (frames réparties sur toute la durée) :\n"
                      f"{res['visual']}\n\nDemande de l'utilisateur : {q}")
            h_yt = history.setdefault(chat_id, [])
            cog = await _cognition_via_api(ctx_yt, h_yt)
            ans = cog["response"] if cog else f"{res['title']} — {res['transcript'][:1500]}"
            h_yt.append(("user", msg))
            h_yt.append(("assistant", ans))
            return "📹 " + ans
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
        h = history.setdefault(chat_id, [])
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
        # Mémoire bornée (consolidator) : au-delà de 16 tours, replie les plus vieux en
        # une synthèse au lieu de les perdre. Bulletproof : repli sûr aux 12 derniers si échec.
        if len(h) > 16:
            try:
                from memory.consolidator import consolidate as _consolidate
                items = [{"content": c, "ts": i, "role": r} for i, (r, c) in enumerate(h)]
                folded = _consolidate(
                    items, max_items=12,
                    summarizer=lambda parts: "Résumé des échanges précédents : "
                    + " | ".join(p[:120] for p in parts)[:800])
                h[:] = [("user", "[" + it["content"] + "]") if it.get("kind") == "summary"
                        else (it["role"], it["content"]) for it in folded]
            except Exception:               # noqa: BLE001
                del h[:len(h) - 12]
        if bus is not None:
            try:
                bus.remember(f"User: {msg}\nBéa: {final}",
                             metadata={"chat_id": str(chat_id), "type": "conversation"},
                             tags=["conversation"])
            except Exception:                # noqa: BLE001
                pass
        return final

    # ── Auto-amélioration avec approbation Telegram (human-in-the-loop) ──
    _pending_improve: dict[str, dict] = {}   # chat_id -> {candidate, score, weakness}

    async def _propose_improvement(chat_id: str) -> str:
        """Détecte une faiblesse + propose le meilleur correctif, en attente de ton 'oui'."""
        def _analyse():
            from core.self_improvement.candidate_generator import get_candidate_generator
            from core.self_improvement.improvement_memory import get_improvement_memory
            from core.self_improvement.improvement_scorer import get_improvement_scorer
            from core.self_improvement.weakness_detector import get_weakness_detector
            w = get_weakness_detector().detect()
            if not w:
                return None, None, None
            cands = get_candidate_generator().generate(w)
            if not cands:
                return w, None, None
            scored = get_improvement_scorer().score_and_rank(
                cands, get_improvement_memory().get_history())
            return w, scored[0][0], scored[0][1]
        try:
            w, top, score = await asyncio.to_thread(_analyse)
        except Exception as e:                # noqa: BLE001
            return f"Erreur d'analyse d'auto-amélioration : {str(e)[:120]}"
        if not w:
            return "Aucune faiblesse détectée — rien à améliorer pour l'instant. 👍"
        if top is None:
            return "Faiblesse détectée mais aucun correctif candidat généré."
        _pending_improve[chat_id] = {"candidate": top, "score": score}
        return (f"🔧 Auto-amélioration proposée\n"
                f"• Faiblesse : {str(w[0])[:110]}\n"
                f"• Correctif : [{getattr(top, 'type', '?')}] {getattr(top, 'description', '')[:160]}\n"
                f"• Score : {score:.2f}\n\n"
                f"J'applique ? Réponds « oui » pour valider, « non » pour annuler.")

    async def _resolve_improvement(chat_id: str, approve: bool) -> str:
        pend = _pending_improve.pop(chat_id, None)
        if pend is None:
            return ""                          # pas de proposition en attente
        if not approve:
            return "Auto-amélioration annulée. 🚫"
        # Ton « oui » via Telegram = approbation OPÉRATEUR -> on lève le garde pour CE changement.
        os.environ["JARVIS_SKIP_IMPROVEMENT_GATE"] = "1"

        def _exec():
            from core.self_improvement.improvement_memory import get_improvement_memory
            from core.self_improvement.safe_executor import get_safe_executor
            res = get_safe_executor().execute(pend["candidate"])
            ok = getattr(res, "success", False)
            rb = getattr(res, "rollback_triggered", False)
            outcome = "SUCCESS" if ok else ("ROLLED_BACK" if rb else "FAILURE")
            get_improvement_memory().record(
                candidate_type=getattr(pend["candidate"], "type", "UNKNOWN"),
                description=getattr(pend["candidate"], "description", "")[:200],
                score=pend["score"], outcome=outcome,
                applied_change=str(getattr(res, "applied_change", ""))[:200])
            return ok, str(getattr(res, "applied_change", "") or getattr(res, "error", ""))[:170]
        try:
            ok, detail = await asyncio.to_thread(_exec)
            return (f"✅ Auto-amélioration appliquée : {detail}" if ok
                    else f"⚠️ Échec/rollback (sécurité a protégé le code) : {detail}")
        except Exception as e:                # noqa: BLE001
            return f"Erreur à l'application : {str(e)[:140]}"
        finally:
            os.environ.pop("JARVIS_SKIP_IMPROVEMENT_GATE", None)

    _IMPROVE_TRIGGER = _re.compile(
        r"\b(am[ée]liore[\s-]?toi|auto[\s-]?am[ée]lior|am[ée]liore ton code|/improve)", _re.I)
    _YES = _re.compile(r"^\s*(oui|ok|vas[\s-]?y|applique|valide|go)\b", _re.I)
    _NO = _re.compile(r"^\s*(non|annule|stop|laisse)\b", _re.I)

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
        if text.startswith(("/stats", "/cout")):
            try:
                from core.observability import get_tracer
                st = get_tracer().stats()
                lines = [f"📊 LLM : {st['calls']} appels · {st['total_tokens']} tokens · "
                         f"erreurs {int(st['error_rate'] * 100)}% · coût ${st['cost_usd']}"]
                lines += [f"  • {m}: {d['calls']} appels" for m, d in st["by_model"].items()]
                return "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                return f"stats indisponibles : {e}"

        # Auto-amélioration : réponse à une proposition en attente (oui/non) — prioritaire.
        if event.chat_id in _pending_improve and (_YES.match(text) or _NO.match(text)):
            resolved = await _resolve_improvement(event.chat_id, bool(_YES.match(text)))
            if resolved:
                return resolved
        # Auto-amélioration : déclencheur explicite.
        if _IMPROVE_TRIGGER.search(text):
            return await _propose_improvement(event.chat_id)

        # Tout le reste -> Béa (mémoire de conversation + mémoire hybride).
        if not text:
            return "Dis-moi quelque chose 🙂"
        try:
            return await _chat(event.chat_id, text)
        except Exception as e:  # noqa: BLE001
            log.exception("chat_failed")
            return f"Erreur : {e}"

    return handler


# ── Indicateur de travail + réponse en UNE bulle (placeholder édité sur place) ──
_THINKING = "🧠 Béa réfléchit…"


async def _tg(client, base_url: str, method: str, payload: dict):
    """Appel API Telegram ; renvoie le 'result' JSON ou None (best-effort)."""
    try:
        r = await client.post(f"{base_url}/{method}", json=payload)
        d = r.json()
        return d.get("result") if d.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


async def _keep_typing(client, base_url: str, chat_id: str) -> None:
    """Maintient l'indicateur '… écrit' tant que Béa travaille (l'action dure ~5 s)."""
    try:
        while True:
            await _tg(client, base_url, "sendChatAction",
                      {"chat_id": chat_id, "action": "typing"})
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _send_reply(client, base_url: str, chat_id: str, msg_id, text: str) -> None:
    """Édite le placeholder avec la réponse finale (UNE seule bulle).
    Ne découpe en messages de suite que si la réponse dépasse la limite Telegram."""
    text = (text or "").strip() or "(aucune réponse)"
    _MAX = 4000
    first, rest = text[:_MAX], text[_MAX:]
    edited = msg_id is not None and await _tg(
        client, base_url, "editMessageText",
        {"chat_id": chat_id, "message_id": msg_id, "text": first})
    if not edited:                       # édition impossible -> message neuf
        await _tg(client, base_url, "sendMessage", {"chat_id": chat_id, "text": first})
    while rest:                          # surplus (réponses très longues) en suite
        chunk, rest = rest[:_MAX], rest[_MAX:]
        await _tg(client, base_url, "sendMessage", {"chat_id": chat_id, "text": chunk})


# ── Vision : analyse de photos via modèle multimodal OpenRouter ──
_VISION_MODEL = os.getenv("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
_VISION_FALLBACK = os.getenv("VISION_FALLBACK",
                             "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")


async def _analyze_photo(client, adapter, file_id: str, question: str) -> str:
    """Télécharge une photo Telegram et l'analyse via un modèle vision OpenRouter."""
    import base64
    rf = await client.get(f"{adapter.base_url}/getFile", params={"file_id": file_id})
    fp = (rf.json().get("result") or {}).get("file_path")
    if not fp:
        return "Impossible de récupérer l'image."
    img = await client.get(f"https://api.telegram.org/file/bot{adapter.token}/{fp}", timeout=30)
    data_url = "data:image/jpeg;base64," + base64.b64encode(img.content).decode()
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return "Clé OpenRouter absente — vision indisponible."
    content = [{"type": "text", "text": question},
               {"type": "image_url", "image_url": {"url": data_url}}]
    for model in (_VISION_MODEL, _VISION_FALLBACK):
        try:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": content}]},
                headers={"Authorization": f"Bearer {key}"}, timeout=90)
            d = resp.json()
            txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            if txt:
                return txt
            log.warning("vision_no_text %s: %s", model, str(d)[:160])
        except Exception as e:  # noqa: BLE001
            log.warning("vision_model_failed %s: %s", model, str(e)[:120])
    return "Désolée, l'analyse de l'image a échoué (modèles vision indisponibles)."


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
                    if not event:
                        _m = upd.get("message") or upd.get("edited_message") or {}
                        # Photo -> analyse vision
                        if _m.get("photo"):
                            _uid = str((_m.get("from") or {}).get("id", ""))
                            if not runner.is_authorized(_uid):
                                continue
                            _cid = str((_m.get("chat") or {}).get("id", ""))
                            _q = _m.get("caption") or "Décris et analyse cette image en détail."
                            _fid = _m["photo"][-1]["file_id"]      # plus haute résolution
                            log.info("photo from %s (légende: %s)", _uid, _q[:60])
                            _ph = await _tg(client, adapter.base_url, "sendMessage",
                                            {"chat_id": _cid, "text": "🖼️ Béa analyse l'image…"})
                            _typing = asyncio.create_task(
                                _keep_typing(client, adapter.base_url, _cid))
                            try:
                                _ans = await _analyze_photo(client, adapter, _fid, _q)
                            except Exception as _e:  # noqa: BLE001
                                _ans = f"Erreur analyse image : {_e}"
                            finally:
                                _typing.cancel()
                            await _send_reply(client, adapter.base_url, _cid,
                                              _ph.get("message_id") if _ph else None, _ans)
                            continue
                        log.info("update ignoré (pas de texte — vocal/autre ?) : champs=%s",
                                 list(_m.keys()))
                        continue
                    log.info("msg from %s: %s", event.user_id, event.text[:80])
                    if not runner.is_authorized(event.user_id):
                        continue                       # allowlist : ignore en silence
                    # 1) placeholder instantané « réfléchit » (= UNE bulle, éditée ensuite)
                    ph = await _tg(client, adapter.base_url, "sendMessage",
                                   {"chat_id": event.chat_id, "text": _THINKING})
                    # 2) indicateur « … écrit » maintenu pendant tout le traitement
                    typing = asyncio.create_task(
                        _keep_typing(client, adapter.base_url, event.chat_id))
                    try:
                        response = await runner.handle(event)
                    finally:
                        typing.cancel()
                    # 3) la réponse REMPLACE le placeholder (pas de nouvelle section)
                    await _send_reply(client, adapter.base_url, event.chat_id,
                                      ph.get("message_id") if ph else None, response)
            except Exception as e:  # noqa: BLE001
                log.warning("poll_error: %s", e)
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
