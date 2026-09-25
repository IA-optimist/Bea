"""Outils filesystem : lecture et écriture de fichiers."""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, field_validator

from tools.base import BEATool
from tools.permissions import PermissionLevel
from tools.result import ToolResult

logger = logging.getLogger(__name__)

_READ_ALLOWED_EXT = {
    ".py", ".ts", ".js", ".json", ".yaml", ".yml", ".toml", ".md",
    ".txt", ".env.example", ".cfg", ".ini", ".sh", ".html", ".css",
}

_WRITE_BLACKLIST = {
    "kernel/runtime/kernel.py",
    "config/settings.py",
    "api/middleware.py",
    "core/policy_engine.py",
}


class ReadFileTool(BEATool):
    name = "read_file"
    description = "Lit le contenu d'un fichier texte depuis le workspace."
    permission = PermissionLevel.AUTO

    class InputSchema(BaseModel):
        path: str
        encoding: str = "utf-8"

        @field_validator("path")
        @classmethod
        def no_traversal(cls, v: str) -> str:
            if ".." in v:
                raise ValueError("Path traversal interdite")
            return v

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        p = Path(input.path)
        if p.suffix not in _READ_ALLOWED_EXT:
            return ToolResult.fail(
                f"Extension '{p.suffix}' non autorisée en lecture. "
                f"Autorisées: {sorted(_READ_ALLOWED_EXT)}"
            )
        if not p.exists():
            return ToolResult.fail(f"Fichier introuvable: {input.path}")
        try:
            content = p.read_text(encoding=input.encoding)
            return ToolResult.ok(output=content, path=str(p), size=len(content))
        except OSError as e:
            return ToolResult.fail(f"Lecture impossible: {e}")


class WriteFileTool(BEATool):
    name = "write_file"
    description = "Écrit du contenu dans un fichier du workspace."
    permission = PermissionLevel.REQUIRES_APPROVAL

    class InputSchema(BaseModel):
        path: str
        content: str
        encoding: str = "utf-8"

        @field_validator("path")
        @classmethod
        def no_traversal(cls, v: str) -> str:
            if ".." in v:
                raise ValueError("Path traversal interdite")
            return v

    async def execute(self, input: InputSchema, context: dict | None = None) -> ToolResult:
        for blocked in _WRITE_BLACKLIST:
            if input.path.endswith(blocked):
                return ToolResult.fail(
                    f"Écriture bloquée sur fichier critique: {input.path}"
                )

        p = Path(input.path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(input.content, encoding=input.encoding)
            return ToolResult.ok(
                output=f"Fichier écrit: {input.path}",
                path=str(p),
                bytes_written=len(input.content.encode(input.encoding)),
            )
        except OSError as e:
            return ToolResult.fail(f"Écriture impossible: {e}")
