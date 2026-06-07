"""
interfaces/ — Adapter boundary between external consumers and BeaMax kernel (Pass 20).

R8: The API is an adapter, never a decision-maker.

This package declares the sanctioned adapter layer. External consumers (HTTP API,
CLI, WebSocket, tests) interact with the system through these adapters.

Rule: adapters translate shapes, never make decisions.
  ✅ Translate HTTP request → ExecutionRequest
  ✅ Translate ExecutionResult → HTTP response
  ✅ Expose kernel.status() without internals
  ❌ Never classify, plan, or route
  ❌ Never bypass kernel.policy()
  ❌ Never import from kernel.runtime directly except through adapters

Available adapters:
    interfaces.kernel_adapter  — wraps kernel.execute() for external consumers
"""
from interfaces.kernel_adapter import KernelAdapter, AdapterResult, get_kernel_adapter

__all__ = ["KernelAdapter", "AdapterResult", "get_kernel_adapter"]
