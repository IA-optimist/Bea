"""BEA MAX v3 — Desktop Environment (Sandbox & Tools)"""
from __future__ import annotations

from executor.desktop_env.sandbox import DockerSandbox, LocalFallbackSandbox, DesktopEnvironment
from executor.desktop_env.terminal import PersistentTerminal
from executor.desktop_env.editor import SurgicalEditor

__all__ = [
    "DesktopEnvironment",
    "DockerSandbox",
    "LocalFallbackSandbox",
    "PersistentTerminal",
    "SurgicalEditor",
]
