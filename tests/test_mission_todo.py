"""Tests du MissionTodoTool."""
import pytest

from tools.mission_todo import (
    TodoWriteTool, TodoReadTool, TodoUpdateTool, TodoAddTool, TodoClearTool,
    _clear_store, _IN_MEMORY_STORE,
)
from tools.result import ToolResult


MISSION_ID = "test-mission-001"

SAMPLE_TODOS = [
    {"id": "1", "content": "Analyser les requirements", "status": "completed"},
    {"id": "2", "content": "Générer le code", "status": "in_progress"},
    {"id": "3", "content": "Écrire les tests", "status": "pending"},
]


@pytest.fixture(autouse=True)
def clean_store():
    _clear_store(MISSION_ID)
    yield
    _clear_store(MISSION_ID)


# ── TodoWrite ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_write_basic():
    tool = TodoWriteTool()
    result = await tool({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    assert result.success
    assert result.metadata["count"] == 3


@pytest.mark.asyncio
async def test_todo_write_auto_assigns_ids():
    tool = TodoWriteTool()
    result = await tool({
        "mission_id": MISSION_ID,
        "todos": [
            {"content": "Task A"},
            {"content": "Task B"},
        ]
    })
    assert result.success
    todos = result.output
    assert todos[0]["id"] == "1"
    assert todos[1]["id"] == "2"


@pytest.mark.asyncio
async def test_todo_write_rejects_invalid_status():
    tool = TodoWriteTool()
    result = await tool({
        "mission_id": MISSION_ID,
        "todos": [{"content": "X", "status": "unknown_status"}]
    })
    assert not result.success
    assert "invalide" in result.error.lower()


@pytest.mark.asyncio
async def test_todo_write_rejects_over_limit():
    tool = TodoWriteTool()
    todos = [{"content": f"Task {i}"} for i in range(51)]
    result = await tool({"mission_id": MISSION_ID, "todos": todos})
    assert not result.success
    assert "Maximum" in result.error


# ── TodoRead ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_read_empty():
    tool = TodoReadTool()
    result = await tool({"mission_id": MISSION_ID})
    assert result.success
    assert result.output == []
    assert result.metadata["count"] == 0


@pytest.mark.asyncio
async def test_todo_read_after_write():
    write = TodoWriteTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    result = await read({"mission_id": MISSION_ID})
    assert result.success
    assert result.metadata["count"] == 3
    assert result.metadata["completed"] == 1
    assert result.metadata["in_progress"] == 1
    assert result.metadata["pending"] == 1


@pytest.mark.asyncio
async def test_todo_read_with_filter():
    write = TodoWriteTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    result = await read({"mission_id": MISSION_ID, "status_filter": "pending"})
    assert result.success
    assert result.metadata["count"] == 1
    assert result.output[0]["content"] == "Écrire les tests"


# ── TodoUpdate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_update_status():
    write = TodoWriteTool()
    update = TodoUpdateTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    result = await update({"mission_id": MISSION_ID, "todo_id": "3", "status": "completed"})
    assert result.success
    assert result.metadata["new_status"] == "completed"


@pytest.mark.asyncio
async def test_todo_update_unknown_id():
    write = TodoWriteTool()
    update = TodoUpdateTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    result = await update({"mission_id": MISSION_ID, "todo_id": "999", "status": "completed"})
    assert not result.success
    assert "introuvable" in result.error


@pytest.mark.asyncio
async def test_todo_update_with_note():
    write = TodoWriteTool()
    update = TodoUpdateTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    await update({
        "mission_id": MISSION_ID,
        "todo_id": "2",
        "status": "cancelled",
        "note": "Hors scope"
    })
    todos = (await read({"mission_id": MISSION_ID})).output
    cancelled = next(t for t in todos if t["id"] == "2")
    assert cancelled["note"] == "Hors scope"


# ── TodoAdd ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_add_appends():
    write = TodoWriteTool()
    add = TodoAddTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    await add({"mission_id": MISSION_ID, "content": "Déployer"})
    result = await read({"mission_id": MISSION_ID})
    assert result.metadata["count"] == 4
    assert result.output[-1]["content"] == "Déployer"


@pytest.mark.asyncio
async def test_todo_add_insert_after():
    write = TodoWriteTool()
    add = TodoAddTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    await add({
        "mission_id": MISSION_ID,
        "content": "Review code",
        "insert_after_id": "2"
    })
    todos = (await read({"mission_id": MISSION_ID})).output
    assert todos[2]["content"] == "Review code"


# ── TodoClear ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_todo_clear():
    write = TodoWriteTool()
    clear = TodoClearTool()
    read = TodoReadTool()
    await write({"mission_id": MISSION_ID, "todos": SAMPLE_TODOS})
    await clear({"mission_id": MISSION_ID})
    result = await read({"mission_id": MISSION_ID})
    assert result.output == []


# ── Workflow complet ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_mission_workflow():
    """Simule le cycle de vie complet d'un agent utilisant les todos."""
    write = TodoWriteTool()
    read = TodoReadTool()
    update = TodoUpdateTool()
    add = TodoAddTool()
    clear = TodoClearTool()

    # 1. Agent initialise son plan
    await write({
        "mission_id": MISSION_ID,
        "todos": [
            {"id": "1", "content": "Lire les fichiers source"},
            {"id": "2", "content": "Analyser les dépendances"},
            {"id": "3", "content": "Générer le code"},
        ]
    })

    # 2. Agent commence la première tâche
    await update({"mission_id": MISSION_ID, "todo_id": "1", "status": "in_progress"})

    # 3. Agent termine la première tâche, découvre une sous-tâche
    await update({"mission_id": MISSION_ID, "todo_id": "1", "status": "completed"})
    await add({"mission_id": MISSION_ID, "content": "Valider les imports", "insert_after_id": "1"})

    # 4. Vérification état intermédiaire
    result = await read({"mission_id": MISSION_ID})
    assert result.metadata["count"] == 4
    assert result.metadata["completed"] == 1

    # 5. Fin de mission : nettoyage
    await clear({"mission_id": MISSION_ID})
    final = await read({"mission_id": MISSION_ID})
    assert final.output == []
