"""
bea-sdk — Python SDK for Bea AI Agent System

A clean, type-safe Python client for interacting with Bea's API and MCP server.
"""
from bea_sdk.client import BeaClient
from bea_sdk.exceptions import BeaError, MemoryError, MissionError
from bea_sdk.memory import MemoryClient
from bea_sdk.mission import MissionClient

__version__ = "0.1.0"
__all__ = [
    "BeaClient",
    "MissionClient",
    "MemoryClient",
    "BeaError",
    "MissionError",
    "MemoryError",
]
