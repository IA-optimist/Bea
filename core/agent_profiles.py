"""Agent Profile Management for BeaMax multi-project specialization."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import structlog
import yaml

log = structlog.get_logger(__name__)


class AgentProfile:
    def __init__(self, data: dict[str, Any]) -> None:
        self.name = cast(str, data.get("name", ""))
        self.system_prompt_additions = cast(list[str], data.get("system_prompt_additions", []))
        self.tools_allowlist = cast(list[str], data.get("tools_allowlist", ["*"]))
        self.tools_denylist = cast(list[str], data.get("tools_denylist", []))
        self.risk_tolerance = float(data.get("risk_tolerance", 0.5))
        self.legal_constraints = cast(list[str], data.get("legal_constraints", []))

    def is_tool_allowed(self, tool: str) -> bool:
        for pattern in self.tools_denylist:
            if pattern == "*" or (pattern.endswith("*") and tool.startswith(pattern[:-1])):
                return False
        if "*" in self.tools_allowlist:
            return True
        for pattern in self.tools_allowlist:
            if pattern == tool or (pattern.endswith("*") and tool.startswith(pattern[:-1])):
                return True
        return False


class AgentProfileLoader:
    _instance: AgentProfileLoader | None = None

    def __new__(cls) -> AgentProfileLoader:
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._profiles = {}
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        paths = [
            Path("/app/config/agent_profiles.yaml"),
            Path(__file__).parent.parent / "config" / "agent_profiles.yaml",
        ]
        for path in paths:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = cast(dict[str, Any], yaml.safe_load(f) or {})
                profiles = cast(dict[str, dict[str, Any]], data.get("profiles", {}))
                for pid, pdata in profiles.items():
                    self._profiles[pid] = AgentProfile(pdata)
                log.info("profiles_loaded", count=len(self._profiles))
                return
        self._profiles["default"] = AgentProfile({"name": "Default", "risk_tolerance": 0.5})

    def get(self, pid: str) -> AgentProfile:
        default = self._profiles.get("default")
        return self._profiles.get(pid, default) if default is not None else self._profiles[pid]


_loader = AgentProfileLoader()


def get_profile(pid: str) -> AgentProfile:
    return _loader.get(pid)
