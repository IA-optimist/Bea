"""
core/tools/tool_os_layer.py — AI OS Tool Layer.

Structured tool descriptors with domains, schemas, error taxonomy,
idempotency safety, and trace logging. Wraps existing tool_executor.

Does NOT replace tool_executor.py — provides OS-level metadata.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional
import logging

log = logging.getLogger("bea.tool_os")


ToolDomain = Literal["filesystem", "network", "analysis", "generation",
                      "communication", "system", "memory"]


@dataclass
class ToolDescriptor:
    """Full AI OS tool descriptor."""
    name: str
    description: str
    domain: ToolDomain
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    timeout_seconds: int = 30
    retry_policy: dict = field(default_factory=lambda: {"max": 1, "backoff": 0.3, "on": ["TRANSIENT", "TIMEOUT"]})
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=lambda: {"ok": "bool", "result": "str", "error": "str?"})
    error_taxonomy: dict = field(default_factory=lambda: {
        "TRANSIENT": "retry", "TIMEOUT": "retry", "USER_INPUT": "fail",
        "TOOL_ERROR": "fail", "POLICY_BLOCKED": "reject", "SYSTEM_ERROR": "fail"
    })
    idempotent: bool = False
    trace_enabled: bool = True
    
    def to_dict(self) -> dict:
        return asdict(self)


# ── Tool Registry ────────────────────────────────────────────────────────────

TOOL_OS_REGISTRY: dict[str, ToolDescriptor] = {}

def _reg(td: ToolDescriptor):
    TOOL_OS_REGISTRY[td.name] = td

# Filesystem domain
_reg(ToolDescriptor(name="file_read", description="Read file contents", domain="filesystem",
                    risk_level="LOW", timeout_seconds=10, idempotent=True,
                    input_schema={"path": "str", "encoding": "str?"}))
_reg(ToolDescriptor(name="file_write", description="Write content to file", domain="filesystem",
                    risk_level="MEDIUM", timeout_seconds=15, idempotent=True,
                    input_schema={"path": "str", "content": "str"}))

# Network domain
_reg(ToolDescriptor(name="web_search", description="Search the web", domain="network",
                    risk_level="LOW", timeout_seconds=15, idempotent=True,
                    input_schema={"query": "str", "max_results": "int?"}))
_reg(ToolDescriptor(name="web_fetch", description="Fetch URL content", domain="network",
                    risk_level="LOW", timeout_seconds=15, idempotent=True,
                    input_schema={"url": "str"}))
_reg(ToolDescriptor(name="http_request", description="Make HTTP request", domain="network",
                    risk_level="MEDIUM", timeout_seconds=20,
                    input_schema={"url": "str", "method": "str", "body": "str?"}))
_reg(ToolDescriptor(name="http_test", description="Test API endpoint", domain="network",
                    risk_level="LOW", timeout_seconds=15, idempotent=True,
                    input_schema={"url": "str", "expected_status": "int?"}))

# Analysis domain
_reg(ToolDescriptor(name="code_execute", description="Execute code safely", domain="analysis",
                    risk_level="HIGH", timeout_seconds=30,
                    input_schema={"code": "str", "language": "str?"}))
_reg(ToolDescriptor(name="browser_navigate", description="Navigate browser", domain="analysis",
                    risk_level="MEDIUM", timeout_seconds=30,
                    input_schema={"url": "str", "action": "str?"}))

# Generation domain
_reg(ToolDescriptor(name="markdown_generate", description="Generate markdown doc", domain="generation",
                    risk_level="LOW", timeout_seconds=15, idempotent=True,
                    input_schema={"title": "str", "content": "str"}))
_reg(ToolDescriptor(name="html_generate", description="Generate HTML", domain="generation",
                    risk_level="LOW", timeout_seconds=15, idempotent=True,
                    input_schema={"template": "str", "data": "dict?"}))
_reg(ToolDescriptor(name="json_schema_generate", description="Generate JSON schema", domain="generation",
                    risk_level="LOW", timeout_seconds=10, idempotent=True,
                    input_schema={"name": "str", "fields": "dict"}))

# Communication domain
_reg(ToolDescriptor(name="email_send", description="Send email", domain="communication",
                    risk_level="MEDIUM", timeout_seconds=20,
                    input_schema={"to": "str", "subject": "str", "body": "str"},
                    idempotent=False))
_reg(ToolDescriptor(name="api_call", description="Call external API", domain="communication",
                    risk_level="MEDIUM", timeout_seconds=20,
                    input_schema={"endpoint": "str", "method": "str", "payload": "dict?"}))

# System domain
_reg(ToolDescriptor(name="shell_execute", description="Execute shell command", domain="system",
                    risk_level="HIGH", timeout_seconds=30,
                    input_schema={"command": "str", "cwd": "str?"},
                    idempotent=False))

# Memory domain
_reg(ToolDescriptor(name="memory_write", description="Write to memory store", domain="memory",
                    risk_level="LOW", timeout_seconds=5,
                    input_schema={"content": "str", "tier": "str", "type": "str?"}))
_reg(ToolDescriptor(name="memory_read", description="Read from memory store", domain="memory",
                    risk_level="LOW", timeout_seconds=5, idempotent=True,
                    input_schema={"query": "str?", "tier": "str?", "limit": "int?"}))


# ── Query API ────────────────────────────────────────────────────────────────

def get_tool(name: str) -> Optional[ToolDescriptor]:
    return TOOL_OS_REGISTRY.get(name)

def list_tools(domain: str = "", risk_level: str = "") -> list[ToolDescriptor]:
    tools = list(TOOL_OS_REGISTRY.values())
    if domain:
        tools = [t for t in tools if t.domain == domain]
    if risk_level:
        tools = [t for t in tools if t.risk_level == risk_level]
    return tools

def list_domains() -> dict[str, list[str]]:
    domains: dict[str, list[str]] = {}
    for t in TOOL_OS_REGISTRY.values():
        domains.setdefault(t.domain, []).append(t.name)
    return domains

def tool_summary() -> dict:
    return {
        "total": len(TOOL_OS_REGISTRY),
        "domains": {d: len(ts) for d, ts in list_domains().items()},
        "by_risk": {
            "LOW": sum(1 for t in TOOL_OS_REGISTRY.values() if t.risk_level == "LOW"),
            "MEDIUM": sum(1 for t in TOOL_OS_REGISTRY.values() if t.risk_level == "MEDIUM"),
            "HIGH": sum(1 for t in TOOL_OS_REGISTRY.values() if t.risk_level == "HIGH"),
        },
    }
