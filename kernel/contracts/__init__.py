"""
kernel/contracts/ — Canonical domain contracts for BeaMax.

These are the primary language of the system. All subsystems communicate
through these typed, validated, serializable objects.
"""
from kernel.contracts.types import (
    Mission, Goal, Plan, PlanStep, Action, Decision,
    Observation, ExecutionResult, PolicyDecision,
    MemoryRecord, SystemEvent, StepType, MissionStatus,
    PlanStatus, RiskLevel, DecisionType,
)
from kernel.contracts.agent import (
    KernelAgentContract, KernelAgentResult, KernelAgentTask,
    KernelAgentStatus, AgentHealthStatus,
    KernelAgentRegistry, get_agent_registry,
)
from kernel.contracts.mission_runner import (
    MissionRunner, MissionCallback,
)

__all__ = [
    # types.py
    "Mission", "Goal", "Plan", "PlanStep", "Action", "Decision",
    "Observation", "ExecutionResult", "PolicyDecision",
    "MemoryRecord", "SystemEvent", "StepType", "MissionStatus",
    "PlanStatus", "RiskLevel", "DecisionType",
    # agent.py (Pass 16)
    "KernelAgentContract", "KernelAgentResult", "KernelAgentTask",
    "KernelAgentStatus", "AgentHealthStatus",
    "KernelAgentRegistry", "get_agent_registry",
    # mission_runner.py (Phase 2 — contract unification)
    "MissionRunner", "MissionCallback",
]
