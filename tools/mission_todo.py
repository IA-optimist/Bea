"""
MissionTodoTool — liste de tâches cognitive pour les agents Béa.
Inspiré de src/tools/TodoWriteTool/ (Claude Code source, 2026-03-31).

Permet aux agents de maintenir un plan structuré pendant l'exécution
d'une mission, en lisant et modifiant une todo-list stockée dans la
working memory du kernel (in-memory, TTL=1h par défaut).

Format de la todo-list :
    [
        {"id": "1", "content": "Analyser les requirements", "status": "completed"},
        {"id": "2", "content": "Générer le code", "status": "in_progress"},
        {"id": "3", "content": "Écrire les tests", "status": "pending"},
    ]

Statuts valides : "pending" | "in_progress" | "completed" | "cancelled"
"""
from __future__ import annotations

import time
import uuid
import logging
from typing import Literal

from pydantic import BaseModel, field_validator

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)

TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]

_KEY_PREFIX = "todo:"
_MAX_TODOS = 50


# ── Store in-memory ────────────────────────────────────────────────────────────

_IN_MEMORY_STORE: dict[str, list[dict]] = {}


def _get_store(mission_id: str) -> list[dict]:
    key = f"{_KEY_PREFIX}{mission_id}"
    return _IN_MEMORY_STORE.get(key, [])


def _set_store(mission_id: str, todos: list[dict]) -> None:
    key = f"{_KEY_PREFIX}{mission_id}"
    _IN_MEMORY_STORE[key] = todos


def _clear_store(mission_id: str) -> None:
    key = f"{_KEY_PREFIX}{mission_id}"
    _IN_MEMORY_STORE.pop(key, None)


# ── Outils ────────────────────────────────────────────────────────────────────

class TodoWriteTool(BEATool):
    """
    Écrit (remplace) la liste de tâches complète d'une mission.
    Utiliser pour initialiser ou réinitialiser le plan de travail.
    """
    name = "todo_write"
    description = (
        "Écrit la liste de tâches complète d'une mission. "
        "Remplace la liste existante. "
        "Utiliser pour initialiser le plan ou après une restructuration majeure."
    )
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str
        todos: list[dict]

        @field_validator("todos")
        @classmethod
        def validate_todos(cls, todos: list[dict]) -> list[dict]:
            if len(todos) > _MAX_TODOS:
                raise ValueError(f"Maximum {_MAX_TODOS} tâches par mission")
            valid_statuses = {"pending", "in_progress", "completed", "cancelled"}
            result = []
            for i, todo in enumerate(todos):
                if "content" not in todo:
                    raise ValueError(f"Tâche {i} manque le champ 'content'")
                result.append({
                    "id": todo.get("id", str(i + 1)),
                    "content": str(todo["content"])[:500],
                    "status": todo.get("status", "pending"),
                    "created_at": todo.get("created_at", time.time()),
                })
                if result[-1]["status"] not in valid_statuses:
                    raise ValueError(
                        f"Statut invalide '{result[-1]['status']}'. "
                        f"Valides: {valid_statuses}"
                    )
            return result

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        _set_store(input.mission_id, input.todos)
        logger.debug(
            "MissionTodo écrite: mission=%s, %d tâches",
            input.mission_id, len(input.todos)
        )
        return ToolResult.ok(
            output=input.todos,
            mission_id=input.mission_id,
            count=len(input.todos),
        )


class TodoReadTool(BEATool):
    """Lit la liste de tâches courante d'une mission."""
    name = "todo_read"
    description = (
        "Lit la liste de tâches courante d'une mission. "
        "Retourne toutes les tâches avec leur statut actuel."
    )
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str
        status_filter: str | None = None

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        todos = _get_store(input.mission_id)

        if input.status_filter:
            todos = [t for t in todos if t.get("status") == input.status_filter]

        return ToolResult.ok(
            output=todos,
            mission_id=input.mission_id,
            count=len(todos),
            pending=sum(1 for t in todos if t.get("status") == "pending"),
            in_progress=sum(1 for t in todos if t.get("status") == "in_progress"),
            completed=sum(1 for t in todos if t.get("status") == "completed"),
        )


class TodoUpdateTool(BEATool):
    """
    Met à jour le statut d'une tâche existante.
    Opération atomique : toutes les mises à jour réussissent ou aucune.
    """
    name = "todo_update"
    description = (
        "Met à jour le statut d'une tâche existante dans la liste. "
        "Utiliser pour marquer une tâche comme 'in_progress', 'completed', ou 'cancelled'."
    )
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str
        todo_id: str
        status: str
        note: str | None = None

        @field_validator("status")
        @classmethod
        def valid_status(cls, v: str) -> str:
            valid = {"pending", "in_progress", "completed", "cancelled"}
            if v not in valid:
                raise ValueError(f"Statut invalide '{v}'. Valides: {valid}")
            return v

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        todos = _get_store(input.mission_id)

        updated = False
        for todo in todos:
            if todo.get("id") == input.todo_id:
                old_status = todo["status"]
                todo["status"] = input.status
                todo["updated_at"] = time.time()
                if input.note:
                    todo["note"] = input.note
                updated = True
                logger.debug(
                    "TodoUpdate: mission=%s id=%s %s→%s",
                    input.mission_id, input.todo_id, old_status, input.status
                )
                break

        if not updated:
            return ToolResult.fail(
                f"Tâche '{input.todo_id}' introuvable dans mission '{input.mission_id}'"
            )

        _set_store(input.mission_id, todos)
        return ToolResult.ok(
            output=todos,
            mission_id=input.mission_id,
            updated_id=input.todo_id,
            new_status=input.status,
        )


class TodoAddTool(BEATool):
    """Ajoute une nouvelle tâche à la liste existante."""
    name = "todo_add"
    description = (
        "Ajoute une nouvelle tâche à la liste de tâches d'une mission. "
        "Utiliser quand une sous-tâche est découverte en cours d'exécution."
    )
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str
        content: str
        status: str = "pending"
        insert_after_id: str | None = None

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        todos = _get_store(input.mission_id)

        if len(todos) >= _MAX_TODOS:
            return ToolResult.fail(
                f"Limite de {_MAX_TODOS} tâches atteinte pour mission '{input.mission_id}'"
            )

        new_todo = {
            "id": str(uuid.uuid4())[:8],
            "content": input.content[:500],
            "status": input.status,
            "created_at": time.time(),
        }

        if input.insert_after_id:
            for i, todo in enumerate(todos):
                if todo.get("id") == input.insert_after_id:
                    todos.insert(i + 1, new_todo)
                    break
            else:
                todos.append(new_todo)
        else:
            todos.append(new_todo)

        _set_store(input.mission_id, todos)
        return ToolResult.ok(
            output=new_todo,
            mission_id=input.mission_id,
            total_count=len(todos),
        )


class TodoClearTool(BEATool):
    """Supprime toutes les tâches d'une mission (fin de mission)."""
    name = "todo_clear"
    description = "Supprime la liste de tâches d'une mission terminée. Libère la working memory."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        _clear_store(input.mission_id)
        return ToolResult.ok(
            output=f"Todo list supprimée pour mission '{input.mission_id}'"
        )


# ── Enregistrement ────────────────────────────────────────────────────────────

TODO_TOOLS = [
    TodoWriteTool(),
    TodoReadTool(),
    TodoUpdateTool(),
    TodoAddTool(),
    TodoClearTool(),
]
