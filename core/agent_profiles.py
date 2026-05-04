"""Agent Profile Management for JarvisMax multi-project specialization."""
import yaml
from pathlib import Path
import structlog

log = structlog.get_logger(__name__)

class AgentProfile:
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.system_prompt_additions = data.get("system_prompt_additions", [])
        self.tools_allowlist = data.get("tools_allowlist", ["*"])
        self.tools_denylist = data.get("tools_denylist", [])
        self.risk_tolerance = data.get("risk_tolerance", 0.5)
        self.legal_constraints = data.get("legal_constraints", [])
    
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
    _instance = None
    _profiles = {}
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance
    
    def _load(self):
        paths = [
            Path("/app/config/agent_profiles.yaml"),
            Path(__file__).parent.parent / "config" / "agent_profiles.yaml"
        ]
        for path in paths:
            if path.exists():
                with open(path) as f:
                    data = yaml.safe_load(f)
                for pid, pdata in data.get("profiles", {}).items():
                    self._profiles[pid] = AgentProfile(pdata)
                log.info("profiles_loaded", count=len(self._profiles))
                return
        self._profiles["default"] = AgentProfile({"name": "Default", "risk_tolerance": 0.5})
    
    def get(self, pid: str):
        return self._profiles.get(pid, self._profiles.get("default"))

_loader = AgentProfileLoader()
def get_profile(pid):
    return _loader.get(pid)
