"""
HexStrike V2 — Modular Penetration Testing Framework

Architecture inspired by Hermes Agent:
- Central tool registry
- Category-based organization
- Risk levels and approval hooks
- Testable, maintainable, scalable

Usage:
    from hexstrike_v2 import registry
    
    # List available tools
    tools = registry.get_all_tools()
    
    # Execute a tool
    result = registry.execute("nmap_scan", {
        "target": "example.com",
        "scan_type": "quick"
    })
    
    # Get stats
    stats = registry.get_stats()
"""
from __future__ import annotations

import logging

# Core imports
from .registry import registry, ToolRegistry

# Auto-import all tool modules to register them
try:
    from . import recon
except ImportError as e:
    logging.warning(f"Failed to import recon tools: {e}")

try:
    from . import scanning
except ImportError as e:
    logging.warning(f"Failed to import scanning tools: {e}")

try:
    from . import web
except ImportError as e:
    logging.warning(f"Failed to import web tools: {e}")

try:
    from . import exploitation
except ImportError as e:
    logging.warning(f"Failed to import exploitation tools: {e}")

try:
    from . import network
except ImportError as e:
    logging.warning(f"Failed to import network tools: {e}")

# Core modules
from .core.executor import CommandExecutor, ExecutionResult, execute_command
from .core.cache import CommandCache, cache
from .core.process_manager import ProcessManager, ProcessStatus, process_manager

# Public API
__all__ = [
    # Registry
    "registry",
    "ToolRegistry",
    
    # Executor
    "CommandExecutor",
    "ExecutionResult",
    "execute_command",
    
    # Cache
    "CommandCache",
    "cache",
    
    # Process Manager
    "ProcessManager",
    "ProcessStatus",
    "process_manager",
]

__version__ = "2.0.0"

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
logger.info(f"HexStrike V2 {__version__} initialized")

# Log registered tools
stats = registry.get_stats()
logger.info(f"Loaded {stats['total_tools']} tools across {len(stats['categories'])} categories")
for category, count in stats['categories'].items():
    logger.info(f"  {category}: {count} tools")
