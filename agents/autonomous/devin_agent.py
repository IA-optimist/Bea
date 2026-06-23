"""
BEA MAX v3 — Devin Agent
Le cerveau autonome. Prend l'Event Stream complet et décide de la prochaine
action à l'aide d'un appel structuré LLM (Function Calling / JSON Schema).
"""
import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from core.events import (
    Action, Observation, TerminalAction, FileReadAction,
    FileWriteAction, FileEditAction, FinishAction,
    SaveMemoryAction,
    PythonExecuteAction, BackgroundAction
)
from core.event_stream import EventStream
# Adaptateur fictif pour utiliser la LLM Factory du projet (ex: OpenAI/Claude)
# En fonction de votre implémentation de `core.llm`.
try:
    from core.llm import LLMFactory
except ImportError:
    LLMFactory = None

log = structlog.get_logger()

SYSTEM_PROMPT = """Tu es BeaMax, un Ingénieur Logiciel Autonome expert.
Tu opères dans une boucle infinie : Réflexion -> Action -> Observation -> Réflexion.
Tu as accès à une machine virtuelle avec un terminal persistant et un éditeur de fichiers.
Règle 1 : Tu dois TOUJOURS utiliser tes outils pour résoudre le problème étape par étape.
Règle 2 : Ne suppose jamais l'état d'un fichier, utilise file_read ou exécute 'ls' / 'cat'.
Règle 3 : Quand tu as totalement fini la mission, appelle l'outil 'finish'.
Règle 4 : Sois concis dans tes réponses.

Format de ta réponse OBLIGATOIRE (JSON pur) :
{
    "thought": "Ta réflexion étape par étape sur ce qu'il faut faire maintenant",
    "action_type": "run_terminal | read_file | write_file | edit_file | browse_web | delegate | save_memory | execute_python | background_job | finish",
    "kwargs": {
        // ... paramètres dépendant de l'action choisie
    }
}
Exemples de kwargs:
- run_terminal: {"command": "npm install"}
- execute_python: {"code": "import sys\\nprint('Hello world!')"}
- read_file: {"file_path": "src/main.py"}
- edit_file: {"file_path": "src/map.py", "old_content": "x = 1\\n", "new_content": "x = 2\\n"}
- browse_web: {"url": "https://react.dev/reference"}
- delegate: {"agent_name": "debug-reviewer", "task": "Trouve l'erreur dans ce stacktrace"}
- save_memory: {"problem_context": "Sur Windows pytest échoue car...", "successful_solution": "Utiliser python -m pytest au lieu de l'exécutable"}
- background_job: {"job_name": "recherche_api_stripe", "task_description": "Trouve la doc pour créer un PaymentIntent en Node.js", "agent_type": "scout"}
- finish: {"success": true, "summary": "J'ai configuré le projet."}
"""

class DevinAgent:
    MATURITY = "experimental"

    def __init__(self, model_hint: str = "gpt-4o"):
        self.model_hint = model_hint
        if LLMFactory:
            self._llm = LLMFactory.get_model(model_hint, temperature=0.2)
        else:
            self._llm = None

        # Mémoire canonique : core.memory_facade fournit l'interface unifiée.
        # Fallback en no-op si la façade est indisponible, pour que l'agent
        # reste instanciable hors LLM / hors mémoire.
        try:
            from core.memory_facade import get_memory_facade

            class _MemoryBank:
                def __init__(self) -> None:
                    self._facade = get_memory_facade()

                def query(self, current_problem: str, limit: int = 2) -> str:
                    try:
                        results = self._facade.search(current_problem, top_k=limit)
                        if not results:
                            return ""
                        out = "\n\n[MÉMOIRE] Il semble que j'ai déjà rencontré un problème similaire :\n"
                        for entry in results:
                            content = getattr(entry, "content", str(entry))
                            out += f"- {content[:300]}\n"
                        return out
                    except Exception as _exc:
                        return ""
        except Exception as _exc:
            class _MemoryBank:
                def query(self, current_problem: str, limit: int = 2) -> str:
                    return ""

        from core.context_manager import ContextCompressor
        self.memory_bank = _MemoryBank()
        self.compressor = ContextCompressor(max_raw_events=12)

    def _format_history(self, stream: EventStream, repo_map: str = "") -> list:
        """Convertit l'EventStream en liste de messages LangChain (avec compression/RAG)."""
        messages = [SystemMessage(content=SYSTEM_PROMPT)]

        if repo_map:
            messages.append(SystemMessage(content=f"CARTE DU PROJET ACTUELLE :\n```\n{repo_map}\n```"))

        events = stream.get_events()

        # Phase 9: Context Compression (Éviter OOM Token)
        summary, recent_events = self.compressor.compress_history(events)

        if summary:
            messages.append(SystemMessage(content=f"RÉSUMÉ DES ANCIENNES ACTIONS:\n{summary}"))

        # Phase 8: RAG Mémoire Épisodique (Déclenchée si la dernière observation est une erreur)
        obs_events = [e for e in recent_events if isinstance(e, Observation)]
        if obs_events and getattr(obs_events[-1], "is_error", False):
            mem_injection = self.memory_bank.query(str(getattr(obs_events[-1], "content", "")))
            if mem_injection:
                 messages.append(SystemMessage(content=mem_injection))

        for e in recent_events:
            if isinstance(e, Action):
                messages.append(AIMessage(content=f"ACTION CHOISIE :\nType: {getattr(e, 'action_type', 'unknown')}\nDetails: {e.model_dump_json()}"))
            elif isinstance(e, Observation):
                status = "Erreur ❌" if getattr(e, "is_error", False) else "Succès ✅"
                messages.append(HumanMessage(content=f"OBSERVATION de l'environnement ({status}):\n```\n{getattr(e, 'content', '')}\n```"))

        # Message final incitant à l'action
        messages.append(HumanMessage(content="C'est à toi. Quelle est la prochaine action (JSON uniquement) ?"))
        return messages

    async def decide_next_action(self, stream: EventStream, repo_map: str = "") -> Action:
        """Appelle le LLM pour générer la prochaine Action."""
        if not self._llm:
            raise RuntimeError("LLMFactory injoignable.")

        messages = self._format_history(stream, repo_map)

        try:
            # Invocation du LLM (on attend un JSON string).
            # Note: en prod v3, on utiliserait le with_structured_output de Langchain.
            # Ici on parse le JSON à la main pour le blueprint.
            response = await self._llm.ainvoke(messages)
            content = response.content.strip()

            # Nettoyage Markdown ```json ... ```
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]

            data = json.loads(content)

            thought = data.get("thought", "")
            action_type = data.get("action_type")
            kwargs = data.get("kwargs", {})

            log.debug("devin_agent_thought", thought=thought[:100])

            # Mapping manuel en attendant un parseur polymorphe Pydantic
            if action_type == "run_terminal":
                return TerminalAction(command=kwargs.get("command", ""), reasoning=thought)
            elif action_type == "read_file":
                return FileReadAction(file_path=kwargs.get("file_path", ""), reasoning=thought)
            elif action_type == "write_file":
                return FileWriteAction(file_path=kwargs.get("file_path", ""), content=kwargs.get("content", ""), reasoning=thought)
            elif action_type == "edit_file":
                return FileEditAction(
                    file_path=kwargs.get("file_path", ""),
                    old_content=kwargs.get("old_content", ""),
                    new_content=kwargs.get("new_content", ""),
                    reasoning=thought
                )
            elif action_type == "save_memory":
                return SaveMemoryAction(
                    problem_context=kwargs.get("problem_context", ""),
                    successful_solution=kwargs.get("successful_solution", ""),
                    reasoning=thought
                )
            elif action_type == "execute_python":
                return PythonExecuteAction(
                    code=kwargs.get("code", ""),
                    reasoning=thought
                )
            elif action_type == "background_job":
                return BackgroundAction(
                    job_name=kwargs.get("job_name", ""),
                    task_description=kwargs.get("task_description", ""),
                    agent_type=kwargs.get("agent_type", "scout"),
                    reasoning=thought
                )
            elif action_type == "finish":
                return FinishAction(success=kwargs.get("success", True), summary=kwargs.get("summary", ""), reasoning=thought)
            else:
                return FinishAction(success=False, summary=f"Agent returned unknown action: {action_type}", reasoning=thought)

        except json.JSONDecodeError:
            log.error("devin_agent_json_error", raw=response.content)
            # En cas de hallucination JSON, on simule une observation d'erreur artificielle pour que l'agent se corrige
            # ou on termine. Pour rester dans le type Action, on fait un finish en échec.
            return FinishAction(success=False, summary="LLM failed to output valid JSON for the action.")
        except Exception as e:
            log.error("devin_agent_fatal", err=str(e))
            return FinishAction(success=False, summary=f"Fatal exception in decide_next_action: {str(e)}")
