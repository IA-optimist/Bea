"""
core.registries — Canonical re-export of the four registries in the repo.

Audit Sprint 3 P1 §3.1 (2026-05-19): the repo has 4 distinct registries
serving different roles, and no top-level package consolidated them. New
code MUST go through this module; do NOT add new registries without
updating this file and the architecture doc.

Hierarchy (READ THIS BEFORE WIRING ANYTHING NEW)
------------------------------------------------

1. **ToolDefinition registry** (`core.tool_registry.ToolRegistry`)
   - Holds metadata: name, description, schema, allowed-callers.
   - Read-only from the agent's perspective.

2. **Tool EXECUTOR registry** (`tools.tool_registry.ToolRegistry`)
   - Holds *live* tool instances and executes them.
   - Pairs each entry with a `ToolResult` envelope.

3. **Operational tools registry** (`core.tools_operational.tool_registry.OperationalToolRegistry`)
   - Tracks externally-installed CLI/HTTP tools (nmap, gh, etc.).
   - JSON-backed, thread-safe singleton.

4. **Agent coordination registry** (`core.agents.agent_registry.AgentRegistry`)
   - Multi-agent messaging + status + role definitions.
   - Carries `AgentMessage`, `AgentStatus`, `MessagePriority`.

Anything else (registries under `orchestrate-cli/`, `business_agents/`, etc.)
is either a local copy for an isolated tool or, per the audit, deprecated.
The audit P1 explicitly recommends freezing the creation of new registries
until this hierarchy is properly enforced.
"""
from __future__ import annotations

# 1. Tool DEFINITIONS
from core.tool_registry import ToolDefinition, ToolRegistry as ToolDefinitionRegistry

# 2. Tool EXECUTOR (live instances + execution)
from tools.tool_registry import ToolRegistry as ToolExecutorRegistry, ToolResult

# 3. Operational tools (external CLI/HTTP tools)
from core.tools_operational.tool_registry import OperationalToolRegistry

# 4. Agent coordination
from core.agents.agent_registry import (
    AgentMessage,
    AgentRegistry,
    AgentStatus,
    MessagePriority,
)

__all__ = [
    # Tool definitions
    "ToolDefinition",
    "ToolDefinitionRegistry",
    # Tool execution
    "ToolExecutorRegistry",
    "ToolResult",
    # Operational tools
    "OperationalToolRegistry",
    # Agent coordination
    "AgentMessage",
    "AgentRegistry",
    "AgentStatus",
    "MessagePriority",
]
