# HexStrike V2 — Migration Guide

## Overview

Refactoring `hexstrike_server.py` (17,289 lines, 156 routes, 183 functions) into a clean modular architecture inspired by Hermes Agent.

**Goals:**
- ✅ Modular design (1 tool = 1 file, ~200-500 lines max)
- ✅ Easy to test (1 tool = 1 test file)
- ✅ Easy to extend (just register new tools)
- ✅ Clean separation of concerns
- ✅ Hermes-compatible tool registry pattern

---

## Architecture

### Directory Structure

```
hexstrike_v2/
├── __init__.py              # Package root + public API
├── registry.py              # Central tool registry (Hermes pattern)
├── server.py                # Flask app (minimal routing only)
├── config.py                # Configuration
│
├── core/                    # Core functionality
│   ├── __init__.py
│   ├── executor.py          # Command execution with retry/timeout
│   ├── cache.py             # Caching layer
│   ├── telemetry.py         # Telemetry & monitoring
│   └── process_manager.py   # Background process management
│
├── recon/                   # Reconnaissance tools
│   ├── __init__.py
│   ├── nmap_tool.py         # ✅ DONE (example)
│   ├── masscan_tool.py
│   ├── subfinder_tool.py
│   ├── amass_tool.py
│   └── ...
│
├── scanning/                # Vulnerability scanners
│   ├── __init__.py
│   ├── nuclei_tool.py
│   ├── nikto_tool.py
│   ├── wpscan_tool.py
│   └── ...
│
├── exploitation/            # Exploit tools (safe, legal only)
│   ├── __init__.py
│   ├── metasploit_tool.py
│   ├── burp_tool.py
│   └── ...
│
├── web/                     # Web-specific tools
│   ├── __init__.py
│   ├── sqlmap_tool.py
│   ├── xss_detector.py
│   ├── dirb_tool.py
│   └── ...
│
├── network/                 # Network tools
│   ├── __init__.py
│   ├── wireshark_tool.py
│   ├── tcpdump_tool.py
│   └── ...
│
├── reporting/               # Report generation
│   ├── __init__.py
│   ├── report_generator.py
│   ├── cvss_calculator.py
│   └── templates/
│
├── utils/                   # Utilities
│   ├── __init__.py
│   ├── files.py             # File operations
│   ├── payloads.py          # Payload generation
│   └── validation.py        # Input validation
│
└── tests/                   # Tests
    ├── test_registry.py
    ├── test_nmap_tool.py
    └── ...
```

---

## Tool Pattern (Hermes-inspired)

Each tool follows this pattern:

```python
"""
Tool Name — Brief description
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..registry import registry
from ..core.executor import execute_command

logger = logging.getLogger(__name__)


def check_tool_installed() -> bool:
    """Check if tool is available"""
    import shutil
    return shutil.which("tool_name") is not None


def tool_function(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tool functionality.
    
    Args:
        params: Tool parameters
    
    Returns:
        Structured result dict
    """
    # Validate params
    required_param = params.get("required_param")
    if not required_param:
        raise ValueError("Missing required parameter: required_param")
    
    # Build command
    command = f"tool_name {required_param}"
    
    # Execute
    result = execute_command(command, timeout=300)
    
    if not result.success:
        raise RuntimeError(f"Tool failed: {result.stderr or result.error}")
    
    # Parse and return
    return {
        "output": result.stdout,
        "duration_seconds": result.duration_seconds,
    }


# Register the tool
registry.register(
    name="tool_name",
    category="recon",  # or scanning, exploitation, web, network
    description="What this tool does",
    handler=tool_function,
    parameters={
        "required_param": {
            "type": "string",
            "required": True,
            "description": "Parameter description"
        },
    },
    risk_level="medium",  # low, medium, high
    requires_approval=True,  # True for dangerous operations
    check_fn=check_tool_installed,
    tags=["tag1", "tag2"],
)
```

---

## Migration Steps

### Phase 1: Core Infrastructure (✅ DONE)

- [x] Create directory structure
- [x] Implement `registry.py` (Hermes pattern)
- [x] Implement `core/executor.py` (command execution)
- [x] Create example tool (`recon/nmap_tool.py`)

### Phase 2: Extract Tools from hexstrike_server.py

**Strategy:** Semi-automated extraction

1. **Identify tool functions** in `hexstrike_server.py`
   - Routes like `/api/tools/nmap` → extract to `recon/nmap_tool.py`
   - Routes like `/api/intelligence/*` → extract to respective categories

2. **For each tool:**
   - Create `<category>/<tool_name>_tool.py`
   - Extract function logic
   - Wrap in tool pattern (see above)
   - Register with registry
   - Write basic test

3. **Tool categories (from analysis):**
   - **Recon (13 routes):** intelligence/smart-scan, bugbounty/reconnaissance, terrascan, etc.
   - **Exploitation (8 routes):** vulnerability-card, attack-chain, vulnerability-hunting, etc.
   - **Web (3 routes):** waybackurls, httpx, http-framework
   - **Network (1 route):** summary-report
   - **Other (100+ routes):** Categorize and extract

### Phase 3: Core Modules

- [ ] `core/cache.py` — Extract caching logic
- [ ] `core/telemetry.py` — Extract telemetry/monitoring
- [ ] `core/process_manager.py` — Extract process management
- [ ] `utils/files.py` — Extract file operations
- [ ] `utils/payloads.py` — Extract payload generation

### Phase 4: Flask Server

- [ ] `server.py` — Minimal Flask app (routing only)
  - All business logic in tools
  - Routes just call `registry.execute(tool_name, params)`
  - Returns JSON responses

### Phase 5: Testing

- [ ] Write tests for each tool
- [ ] Integration tests for server
- [ ] Load testing

### Phase 6: Update MCP Client

- [ ] Update `hexstrike_mcp.py` to use new structure
- [ ] Ensure backward compatibility if needed

### Phase 7: Documentation

- [ ] Update README
- [ ] API documentation (OpenAPI/Swagger)
- [ ] Tool catalog (auto-generated from registry)

---

## Benefits

| Before | After |
|--------|-------|
| 17,289 lines in 1 file | ~200-500 lines per module |
| 156 routes mixed with logic | Routes separate from logic |
| Hard to test | 1 tool = 1 test file |
| Hard to extend | Just register new tool |
| No tool discovery | Registry with categories, tags |
| No risk levels | Each tool has risk_level |
| No approval system | Requires_approval flag per tool |

---

## Usage Examples

### Basic Tool Execution

```python
from hexstrike_v2 import registry

# Execute a tool
result = registry.execute("nmap_scan", {
    "target": "example.com",
    "scan_type": "quick"
})

if result["success"]:
    print(result["data"]["summary"])
else:
    print(f"Error: {result['error']}")
```

### List Available Tools

```python
from hexstrike_v2 import registry

# Get all tools
all_tools = registry.get_all_tools()
for tool in all_tools:
    print(f"{tool.name} ({tool.category}) - {tool.description}")

# Get recon tools only
recon_tools = registry.get_tools_by_category("recon")

# Get stats
stats = registry.get_stats()
print(f"Total tools: {stats['total_tools']}")
print(f"By category: {stats['categories']}")
```

### Flask Server Integration

```python
from flask import Flask, request, jsonify
from hexstrike_v2 import registry

app = Flask(__name__)

@app.route("/api/tools/<tool_name>", methods=["POST"])
def execute_tool(tool_name):
    """Execute a tool by name"""
    params = request.get_json()
    result = registry.execute(tool_name, params)
    return jsonify(result)

@app.route("/api/tools", methods=["GET"])
def list_tools():
    """List all available tools"""
    tools = registry.get_all_tools()
    return jsonify([
        {
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "risk_level": t.risk_level,
        }
        for t in tools
    ])
```

---

## Next Steps

1. **Extract remaining tools** from `hexstrike_server.py`
   - Start with high-value tools (recon, scanning)
   - Then exploitation, web, network
   - Finally utilities

2. **Implement core modules** (cache, telemetry, process_manager)

3. **Write tests** for each tool

4. **Create minimal Flask server** (`server.py`)

5. **Update hexstrike_mcp.py** to use new structure

6. **Deprecate `hexstrike_server.py`** (keep as `legacy/hexstrike_server.py`)

---

## Timeline

- **Week 1:** Core infrastructure + 20 high-priority tools
- **Week 2:** Remaining tools + core modules + tests
- **Week 3:** Flask server + MCP client update + documentation
- **Week 4:** Testing, optimization, deployment

---

## Notes

- Keep `hexstrike_server.py` as `legacy/hexstrike_server.py` for reference
- Maintain backward compatibility in MCP client if needed
- Each tool should be self-contained and testable
- Use type hints everywhere
- Write docstrings for all public functions
- Log everything (use `logging` module)

---

**Status:** Phase 1 complete ✅  
**Next:** Extract tools from hexstrike_server.py (Phase 2)
