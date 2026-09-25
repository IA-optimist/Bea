"""Enregistrement des outils worktree dans le registry builtin."""
from tools.git_worktree import EnterWorktreeTool, ExitWorktreeTool, ListWorktreesTool

WORKTREE_TOOLS = [EnterWorktreeTool(), ExitWorktreeTool(), ListWorktreesTool()]
