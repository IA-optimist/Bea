"""Outil shell — exécution de commandes avec contrôles de sécurité."""
from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, field_validator

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)

_BLOCKED_COMMANDS = {
    "rm -rf /", "dd if=", "mkfs", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff",
}

_DEFAULT_TIMEOUT = 30


class RunCommandTool(BEATool):
    name = "run_command"
    description = "Exécute une commande shell dans le répertoire courant."
    permission = PermissionLevel.REQUIRES_APPROVAL

    class InputSchema(BaseModel):
        command: str
        cwd: str | None = None
        timeout: int = _DEFAULT_TIMEOUT
        env: dict[str, str] | None = None

        @field_validator("command")
        @classmethod
        def no_blocked(cls, v: str) -> str:
            for blocked in _BLOCKED_COMMANDS:
                if blocked in v:
                    raise ValueError(f"Commande bloquée: '{blocked}'")
            return v

        @field_validator("timeout")
        @classmethod
        def cap_timeout(cls, v: int) -> int:
            return min(max(v, 1), 300)

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                input.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=input.cwd,
                env=input.env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=input.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult.fail(
                    f"Commande timeout après {input.timeout}s: {input.command}"
                )

            stdout_str = stdout.decode(errors="replace").strip()
            stderr_str = stderr.decode(errors="replace").strip()
            success = proc.returncode == 0

            return ToolResult(
                success=success,
                output=stdout_str,
                error=stderr_str if not success else None,
                metadata={
                    "returncode": proc.returncode,
                    "stderr": stderr_str,
                    "command": input.command,
                },
            )
        except Exception as e:
            return ToolResult.fail(f"Échec exécution: {e}")
