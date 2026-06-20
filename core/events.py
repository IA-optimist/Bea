"""
BEA MAX v3 — Événements et Actions (Event Sourcing)
Schémas Pydantic immuables pour modéliser tout l'historique d'une mission.
"""
import uuid
import time
from typing import Any, Literal, Union
from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# BASE EVENTS
# ═══════════════════════════════════════════════════════════════

class Event(BaseModel):  # type: ignore[misc]
    """Objet de base immuable pour tout événement du système."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    source: str = "system"  # ex: 'agent', 'sandbox', 'user', 'system'

class Observation(Event):
    """Résultat renvoyé par l'environnement ou l'utilisateur après une action."""
    observation_type: str = "generic"
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

class Action(Event):
    """Décision prise par l'agent ou l'utilisateur pour modifier l'état ou le monde."""
    action_type: str = "generic"
    reasoning: str = ""  # La réflexion de l'agent qui a conduit à cette action (Thought)

# ═══════════════════════════════════════════════════════════════
# OBSERVATIONS SPÉCIFIQUES
# ═══════════════════════════════════════════════════════════════

class NullObservation(Observation):
    observation_type: Literal["null"] = "null"
    content: str = ""

class TerminalObservation(Observation):
    observation_type: Literal["terminal"] = "terminal"
    exit_code: int = 0

class FileObservation(Observation):
    observation_type: Literal["file"] = "file"
    file_path: str = ""

class BrowserObservation(Observation):
    observation_type: Literal["browser_obs"] = "browser_obs"
    url: str

class PythonObservation(Observation):
    observation_type: Literal["python_obs"] = "python_obs"
    exit_code: int

class BackgroundObservation(Observation):
    """(Phase 13) Observation émise de manière asynchrone par un job de fond."""
    observation_type: Literal["background_obs"] = "background_obs"
    job_id: str
    job_name: str
    status: str # 'running', 'completed', 'failed'

class SaveMemoryAction(Action):
    """(Phase 8) Permet à l'agent de consolider explicitement une notion acquise."""
    action_type: Literal["save_memory"] = "save_memory"
    problem_context: str
    successful_solution: str

class PythonExecuteAction(Action):
    """(Phase 10) Permet à l'agent d'exécuter du code Python natif."""
    action_type: Literal["execute_python"] = "execute_python"
    code: str

# ═══════════════════════════════════════════════════════════════
# ACTIONS SPÉCIFIQUES (Tool Calling)
# ═══════════════════════════════════════════════════════════════

class TerminalAction(Action):
    """Exécute une commande dans le terminal (Sandbox)."""
    action_type: Literal["run_terminal"] = "run_terminal"
    command: str

class FileReadAction(Action):
    """Lit le contenu d'un fichier."""
    action_type: Literal["read_file"] = "read_file"
    file_path: str
    start_line: int | None = None
    end_line: int | None = None

class FileWriteAction(Action):
    """Écrit ou remplace un fichier entier."""
    action_type: Literal["write_file"] = "write_file"
    file_path: str
    content: str

class FileEditAction(Action):
    """Édition chirurgicale d'un fichier (str_replace)."""
    action_type: Literal["edit_file"] = "edit_file"
    file_path: str
    old_content: str  # Le texte exact à chercher et remplacer
    new_content: str  # Le texte de remplacement

class BrowserNavigateAction(Action):
    """Ouvre une URL dans le navigateur sandboxé."""
    action_type: Literal["browser_navigate"] = "browser_navigate"
    url: str

class DelegateAction(Action):
    """Délègue une sous-tâche à un autre agent spécialisé."""
    action_type: Literal["delegate"] = "delegate"
    agent_name: str
    task: str

class BackgroundAction(Action):
    """(Phase 13) Lance une tâche asynchrone qui tournera en parallèle."""
    action_type: Literal["background_job"] = "background_job"
    job_name: str
    task_description: str
    agent_type: str = "scout" # par défaut un chercheur asynchrone

class MessageAction(Action):
    """Envoie un message (à l'utilisateur ou logge une note)."""
    action_type: Literal["message"] = "message"
    message: str

class FinishAction(Action):
    """L'agent déclare que sa mission est terminée (succès ou abandon)."""
    action_type: Literal["finish"] = "finish"
    success: bool = True
    summary: str = ""

# Type d'union pour parsing facile
AnyAction = Union[
    TerminalAction,
    FileReadAction,
    FileWriteAction,
    FileEditAction,
    BrowserNavigateAction,
    DelegateAction,
    BackgroundAction,
    MessageAction,
    FinishAction,
    Action, # Fallback
]

AnyObservation = Union[
    TerminalObservation,
    FileObservation,
    BrowserObservation,
    BackgroundObservation,
    NullObservation,
    Observation, # Fallback
]
