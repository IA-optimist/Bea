"""
Git Worktree isolation pour les missions build.
Inspiré de src/tools/EnterWorktreeTool/ et ExitWorktreeTool/ (Claude Code, 2026-03-31).

Usage pattern :
    async with WorktreeContext(mission_id="abc123") as wt:
        # wt.path  → répertoire isolé
        # wt.branch → "bea/mission-abc123"
        await do_build_work(wt.path)
    # Après le bloc : worktree supprimé, branche optionnellement mergée
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)

_WORKTREE_BASE = Path(".bea_worktrees")
_BRANCH_PREFIX = "bea/mission-"


def _sanitize_id(mission_id: str) -> str:
    """Nettoie le mission_id pour usage dans un nom de branche git."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", mission_id)[:40]


async def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Exécute une commande git et retourne (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


@dataclass
class WorktreeInfo:
    mission_id: str
    branch: str
    path: Path
    created: bool = False


@dataclass
class WorktreeContext:
    """
    Context manager pour isolation git worktree.

    async with WorktreeContext(mission_id="abc123") as wt:
        # wt.path est le répertoire isolé
        # wt.branch est la branche git
    """
    mission_id: str
    auto_cleanup: bool = True
    _info: WorktreeInfo | None = field(default=None, init=False, repr=False)

    async def __aenter__(self) -> WorktreeInfo:
        safe_id = _sanitize_id(self.mission_id)
        branch = f"{_BRANCH_PREFIX}{safe_id}"
        worktree_path = _WORKTREE_BASE / safe_id

        _WORKTREE_BASE.mkdir(exist_ok=True)

        rc, _, err = await _git(["worktree", "add", "-b", branch, str(worktree_path)])
        if rc != 0:
            # La branche existe peut-être déjà (reprise de mission)
            rc2, _, err2 = await _git(
                ["worktree", "add", str(worktree_path), branch]
            )
            if rc2 != 0:
                raise RuntimeError(
                    f"Impossible de créer le worktree pour {self.mission_id}: {err2 or err}"
                )

        self._info = WorktreeInfo(
            mission_id=self.mission_id,
            branch=branch,
            path=worktree_path,
            created=True,
        )
        logger.info("Worktree créé: %s à %s", branch, worktree_path)
        return self._info

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._info and self.auto_cleanup:
            await _cleanup_worktree(self._info)
        return False


async def _cleanup_worktree(info: WorktreeInfo) -> None:
    """Supprime le worktree et la branche associée."""
    rc, _, err = await _git(["worktree", "remove", "--force", str(info.path)])
    if rc != 0:
        logger.warning("git worktree remove failed: %s", err)
        if info.path.exists():
            shutil.rmtree(info.path, ignore_errors=True)

    rc2, _, err2 = await _git(["branch", "-D", info.branch])
    if rc2 != 0:
        logger.warning("git branch -D failed for %s: %s", info.branch, err2)

    logger.info("Worktree nettoyé: %s", info.branch)


# ── BEATool wrappers ────────────────────────────────────────────────────────

class EnterWorktreeTool(BEATool):
    """
    Crée un git worktree isolé pour une mission build.
    Retourne le path et la branche dans ToolResult.metadata.
    """
    name = "enter_worktree"
    description = (
        "Crée un git worktree isolé pour une mission build. "
        "Retourne le chemin du répertoire de travail isolé."
    )
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        safe_id = _sanitize_id(input.mission_id)
        branch = f"{_BRANCH_PREFIX}{safe_id}"
        worktree_path = _WORKTREE_BASE / safe_id

        _WORKTREE_BASE.mkdir(exist_ok=True)

        rc, _, err = await _git(["worktree", "add", "-b", branch, str(worktree_path)])
        if rc != 0:
            rc2, _, err2 = await _git(["worktree", "add", str(worktree_path), branch])
            if rc2 != 0:
                return ToolResult.fail(f"Création worktree échouée: {err2 or err}")

        logger.info("Worktree ouvert: %s à %s", branch, worktree_path)
        return ToolResult.ok(
            output=f"Worktree prêt: {worktree_path}",
            worktree_path=str(worktree_path),
            branch=branch,
            mission_id=input.mission_id,
        )


class ExitWorktreeTool(BEATool):
    """Supprime un git worktree existant et sa branche."""
    name = "exit_worktree"
    description = "Supprime le git worktree isolé d'une mission et nettoie la branche."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        mission_id: str
        merge_to_main: bool = False

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        safe_id = _sanitize_id(input.mission_id)
        branch = f"{_BRANCH_PREFIX}{safe_id}"
        worktree_path = _WORKTREE_BASE / safe_id

        if input.merge_to_main:
            rc, _, err = await _git(["merge", "--no-ff", branch, "-m",
                                      f"Merge mission {input.mission_id}"])
            if rc != 0:
                return ToolResult.fail(f"Merge échoué avant cleanup: {err}")
            logger.info("Branch mergée: %s → main", branch)

        info = WorktreeInfo(
            mission_id=input.mission_id,
            branch=branch,
            path=worktree_path,
        )
        await _cleanup_worktree(info)
        return ToolResult.ok(output=f"Worktree supprimé: {branch}")


class ListWorktreesTool(BEATool):
    """Liste les worktrees actifs (missions en cours)."""
    name = "list_worktrees"
    description = "Liste les git worktrees actifs (missions build en cours)."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        pass

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        rc, out, err = await _git(["worktree", "list", "--porcelain"])
        if rc != 0:
            return ToolResult.fail(f"git worktree list échoué: {err}")

        worktrees = []
        current: dict = {}
        for line in out.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[9:]}
            elif line.startswith("branch "):
                current["branch"] = line[7:]
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
        if current:
            worktrees.append(current)

        bea_worktrees = [w for w in worktrees if _BRANCH_PREFIX in w.get("branch", "")]
        return ToolResult.ok(output=bea_worktrees, count=len(bea_worktrees))
