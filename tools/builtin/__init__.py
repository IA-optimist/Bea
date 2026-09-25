"""
Auto-enregistrement de tous les outils builtin dans le ToolRegistry.
Importer ce module au démarrage de l'API (dans api/main.py ou core/__init__.py).
"""
from tools import registry
from tools.builtin.filesystem import ReadFileTool, WriteFileTool
from tools.builtin.shell import RunCommandTool
from tools.builtin.http_client import HttpGetTool, HttpPostTool
from tools.builtin.search import WebSearchTool
from tools.builtin.worktree import WORKTREE_TOOLS
from tools.mission_todo import TODO_TOOLS


def register_builtin_tools() -> None:
    """Enregistre tous les outils builtin. Appeler au démarrage."""
    tools = [
        ReadFileTool(),
        WriteFileTool(),
        RunCommandTool(),
        HttpGetTool(),
        HttpPostTool(),
        WebSearchTool(),
        *WORKTREE_TOOLS,
        *TODO_TOOLS,
    ]
    for tool in tools:
        registry.register(tool)


register_builtin_tools()
