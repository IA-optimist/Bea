"""
core/policy/control_profiles.py — AI OS Human Control Layer.

Defines 3 policy profiles (safe, balanced, autonomous) that control
Jarvis's autonomy level. Integrates with existing policy_engine.py.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal
import logging

log = logging.getLogger("jarvis.control")

ProfileName = Literal["safe", "balanced", "autonomous"]


@dataclass
class ControlProfile:
    """A policy profile defining autonomy boundaries."""
    name: ProfileName
    description: str
    max_risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    tools_requiring_approval: tuple[str, ...] = ()
    auto_execution_budget_usd: float = 0.50
    auto_execution_max_steps: int = 5
    memory_write_allowed: bool = True
    system_modification_allowed: bool = False
    
    def allows_risk(self, risk_level: str) -> bool:
        risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        return risk_order.get(risk_level, 3) <= risk_order.get(self.max_risk_level, 1)
    
    def requires_approval(self, tool_name: str) -> bool:
        if self.name == "safe":
            return True  # Everything needs approval in safe mode
        return tool_name in self.tools_requiring_approval
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["tools_requiring_approval"] = list(self.tools_requiring_approval)
        return d


# ── Profile Definitions ──────────────────────────────────────────────────────

PROFILES: dict[ProfileName, ControlProfile] = {
    "safe": ControlProfile(
        name="safe",
        description="Maximum human oversight. All actions require approval.",
        max_risk_level="LOW",
        tools_requiring_approval=("shell_execute", "code_execute", "file_write",
                                   "email_send", "api_call", "http_request",
                                   "memory_write", "browser_navigate"),
        auto_execution_budget_usd=0.10,
        auto_execution_max_steps=3,
        memory_write_allowed=True,
        system_modification_allowed=False,
    ),
    "balanced": ControlProfile(
        name="balanced",
        description="Standard operation. HIGH risk tools require approval.",
        max_risk_level="HIGH",
        tools_requiring_approval=("shell_execute", "code_execute"),
        auto_execution_budget_usd=1.00,
        auto_execution_max_steps=10,
        memory_write_allowed=True,
        system_modification_allowed=False,
    ),
    "autonomous": ControlProfile(
        name="autonomous",
        description="Maximum autonomy. Only CRITICAL actions need approval.",
        max_risk_level="HIGH",
        tools_requiring_approval=(),  # None — all auto-approved
        auto_execution_budget_usd=5.00,
        auto_execution_max_steps=20,
        memory_write_allowed=True,
        system_modification_allowed=False,  # Never auto-modify core
    ),
}

# ── Active profile ────────────────────────────────────────────────────────────

_active_profile: ProfileName = "balanced"

def get_active_profile() -> ControlProfile:
    return PROFILES[_active_profile]

def set_active_profile(name: ProfileName) -> ControlProfile:
    global _active_profile
    if name not in PROFILES:
        raise ValueError(f"Unknown profile: {name}. Valid: {list(PROFILES.keys())}")
    _active_profile = name
    log.info("control_profile_changed", profile=name)
    return PROFILES[name]

def list_profiles() -> list[dict]:
    return [p.to_dict() for p in PROFILES.values()]
