"""
Isolation des missions build via git worktrees.
À utiliser dans core/orchestration/business_missions.py.
"""
from __future__ import annotations

import logging
from typing import Callable, Awaitable, Any

from tools.git_worktree import WorktreeContext

logger = logging.getLogger(__name__)


async def run_in_worktree(
    mission_id: str,
    build_fn: Callable[[str], Awaitable[Any]],
    auto_cleanup: bool = True,
) -> Any:
    """
    Exécute build_fn dans un git worktree isolé.

    Args:
        mission_id : ID unique de la mission (utilisé pour nommer la branche)
        build_fn   : coroutine prenant le path du worktree en argument
        auto_cleanup : si True, supprime le worktree après exécution

    Returns:
        Le résultat de build_fn

    Usage dans handle_build_product :
        result = await run_in_worktree(
            mission_id=mission_id,
            build_fn=lambda path: forge_builder.build(goal, output_dir=path),
        )
    """
    async with WorktreeContext(mission_id=mission_id, auto_cleanup=auto_cleanup) as wt:
        logger.info(
            "Mission %s: démarrage build dans worktree %s (branche: %s)",
            mission_id, wt.path, wt.branch,
        )
        result = await build_fn(str(wt.path))
        logger.info("Mission %s: build terminé", mission_id)
        return result
