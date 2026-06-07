"""
BEA MAX — executor package
Canonical execution layer.

CANONICAL EXPORTS:
  ExecutionResult    — from executor.contracts (THE one result model)
  ErrorClass         — from executor.contracts (error taxonomy)
  ExecutionTask      — from executor.task_model (task input model)
  ExecutionEngine    — from executor.execution_engine (pipeline)
  RetryPolicy        — from executor.retry_policy (retry config)

ENTRY POINTS:
  get_engine()       — ExecutionEngine singleton
  classify_error()   — error string → ErrorClass
  is_retryable()     — ErrorClass → bool
"""
# Canonical result model
from executor.contracts import (
    ExecutionResult,
    ExecutionStatus,
    ErrorClass,
    classify_error,
    is_retryable,
)

# Task input model
from executor.task_model import (
    ExecutionTask,
    STATUS_PENDING, STATUS_RUNNING, STATUS_SUCCEEDED,
    STATUS_FAILED, STATUS_CANCELLED, STATUS_TIMED_OUT,
)

# Execution engine
from executor.execution_engine import ExecutionEngine, get_engine, reset_engine

# Retry policy
from executor.retry_policy import RetryPolicy, DEFAULT_POLICY, FAST_POLICY, should_retry, compute_delay

# Handlers
from executor.handlers import get_handler, HANDLER_REGISTRY

__all__ = [
    # Canonical contracts
    "ExecutionResult", "ExecutionStatus", "ErrorClass",
    "classify_error", "is_retryable",
    # Task model
    "ExecutionTask",
    "STATUS_PENDING", "STATUS_RUNNING", "STATUS_SUCCEEDED",
    "STATUS_FAILED", "STATUS_CANCELLED", "STATUS_TIMED_OUT",
    # Engine
    "ExecutionEngine", "get_engine", "reset_engine",
    # Retry
    "RetryPolicy", "DEFAULT_POLICY", "FAST_POLICY",
    "should_retry", "compute_delay",
    # Handlers
    "get_handler", "HANDLER_REGISTRY",
]
