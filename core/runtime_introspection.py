"""
JARVIS MAX — Runtime Introspection
====================================
Unified self-awareness layer for JarvisMax.

Provides:
1. get_runtime_capabilities() — full runtime capability map (stable JSON)
2. check_tool_health(tool_name) — per-tool health status
3. Enhanced error classification
4. Execution signal recording (passive, no behavior influence)

Design:
- Every function is fail-open (returns safe defaults, never raises)
- Zero external dependencies (stdlib + optional structlog)
- Stable output schema — fields are always present, values may be empty
- Missing capabilities produce {"available": False} not exceptions

Usage:
    from core.runtime_introspection import (
        get_runtime_capabilities,
        check_tool_health,
        classify_error,
        record_execution_signal,
        get_execution_signals,
    )
    caps = get_runtime_capabilities()
    health = check_tool_health("read_file")
    category = classify_error(some_exception)
"""
from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
_silent_log = __import__("structlog").get_logger(__name__)

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PRIORITY 1 — RUNTIME CAPABILITY MAP
# ═══════════════════════════════════════════════════════════════

@dataclass
class Capability:
    """A single runtime capability detection result.

    Attributes:
        name: Capability identifier (e.g. "python", "docker", "network").
        available: Whether the capability is present and functional.
        version: Version string if applicable.
        detail: Additional human-readable information.
        meta: Arbitrary key-value metadata.
    """
    name:      str
    available: bool = False
    version:   str  = ""
    detail:    str  = ""
    meta:      dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "version": self.version,
            "detail": self.detail,
            "meta": self.meta,
        }


def _detect_python() -> Capability:
    """Detect Python version and implementation."""
    try:
        v = sys.version_info
        return Capability(
            name="python",
            available=True,
            version=f"{v.major}.{v.minor}.{v.micro}",
            detail=sys.implementation.name,
            meta={
                "major": v.major, "minor": v.minor, "micro": v.micro,
                "implementation": sys.implementation.name,
                "executable": sys.executable,
                "min_supported": "3.10",
                "compatible": v >= (3, 10),
            },
        )
    except Exception as e:
        return Capability(name="python", detail=f"detection failed: {str(e)[:100]}")


def _detect_packages() -> Capability:
    """Detect installed Python packages."""
    try:
        # Use importlib.metadata (stdlib, Python 3.8+)
        from importlib.metadata import distributions
        pkgs = {}
        for dist in distributions():
            pkgs[dist.metadata["Name"]] = dist.metadata["Version"]
        return Capability(
            name="packages",
            available=True,
            version=f"{len(pkgs)} packages",
            detail=", ".join(sorted(pkgs.keys())[:20]),
            meta={"count": len(pkgs), "packages": pkgs},
        )
    except Exception as e:
        return Capability(name="packages", detail=f"detection failed: {str(e)[:100]}")


def _detect_tools() -> Capability:
    """Detect available JarvisMax tools from tool registry."""
    try:
        from core.tool_registry import get_tool_registry
        reg = get_tool_registry()
        tools = reg.list_tools()
        tool_names = [t.name for t in tools]
        return Capability(
            name="tools",
            available=len(tools) > 0,
            version=f"{len(tools)} tools",
            detail=", ".join(tool_names[:15]),
            meta={"count": len(tools), "tools": tool_names},
        )
    except Exception as e:
        return Capability(name="tools", detail=f"registry unavailable: {str(e)[:100]}")


def _detect_filesystem() -> Capability:
    """Detect filesystem access scope."""
    try:
        cwd = os.getcwd()
        home = str(Path.home())
        writable = os.access(cwd, os.W_OK)
        tmp_writable = os.access("/tmp", os.W_OK)  # nosec B108 — probe (no write); just reports whether /tmp is writable.
        disk_usage = shutil.disk_usage(cwd)
        free_gb = round(disk_usage.free / (1024**3), 1)
        return Capability(
            name="filesystem",
            available=True,
            detail=f"cwd={cwd}, writable={writable}",
            meta={
                "cwd": cwd,
                "home": home,
                "cwd_writable": writable,
                "tmp_writable": tmp_writable,
                "free_gb": free_gb,
                "total_gb": round(disk_usage.total / (1024**3), 1),
            },
        )
    except Exception as e:
        return Capability(name="filesystem", detail=f"detection failed: {str(e)[:100]}")


def _detect_network() -> Capability:
    """Detect basic network availability (DNS resolution only, no external calls)."""
    try:
        # Try DNS resolution — lightweight, no actual connection
        socket.setdefaulttimeout(2)
        socket.getaddrinfo("dns.google", 443, socket.AF_INET)
        hostname = socket.gethostname()
        return Capability(
            name="network",
            available=True,
            detail=f"DNS resolves, hostname={hostname}",
            meta={
                "dns_resolves": True,
                "hostname": hostname,
            },
        )
    except (socket.gaierror, socket.timeout, OSError):
        return Capability(
            name="network",
            available=False,
            detail="DNS resolution failed — network may be unavailable",
            meta={"dns_resolves": False},
        )
    except Exception as e:
        return Capability(name="network", detail=f"detection failed: {str(e)[:100]}")


def _detect_docker() -> Capability:
    """Detect Docker availability."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return Capability(
                name="docker",
                available=True,
                version=version,
                detail="Docker daemon reachable",
                meta={"server_version": version},
            )
        return Capability(
            name="docker",
            available=False,
            detail=f"Docker returned exit code {result.returncode}",
            meta={"stderr": result.stderr.strip()[:200]},
        )
    except FileNotFoundError:
        return Capability(name="docker", available=False, detail="docker binary not found")
    except subprocess.TimeoutExpired:
        return Capability(name="docker", available=False, detail="docker command timed out")
    except Exception as e:
        return Capability(name="docker", detail=f"detection failed: {str(e)[:100]}")


def _detect_git() -> Capability:
    """Detect Git availability and repo state."""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "--version"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip().replace("git version ", "")
            # Check if we're in a repo
            branch_result = subprocess.run(  # nosec B603 B607
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
            return Capability(
                name="git",
                available=True,
                version=version,
                detail=f"branch={branch}" if branch else "not in a repo",
                meta={"version": version, "branch": branch, "in_repo": bool(branch)},
            )
        return Capability(name="git", available=False, detail="git not functional")
    except FileNotFoundError:
        return Capability(name="git", available=False, detail="git binary not found")
    except Exception as e:
        return Capability(name="git", detail=f"detection failed: {str(e)[:100]}")


def _detect_optional_modules() -> Capability:
    """Detect availability of optional Python modules used by JarvisMax."""
    modules = {
        "structlog": False, "pydantic": False, "requests": False,
        "fastapi": False, "uvicorn": False, "langchain_core": False,
        "qdrant_client": False, "redis": False, "openai": False,
        "anthropic": False,
    }
    for mod in modules:
        try:
            importlib.import_module(mod)
            modules[mod] = True
        except ImportError:
            _silent_log.debug("suppressed_exception", src='runtime_introspection.py')
    available_count = sum(1 for v in modules.values() if v)
    return Capability(
        name="optional_modules",
        available=available_count > 0,
        version=f"{available_count}/{len(modules)}",
        detail=", ".join(k for k, v in modules.items() if v) or "none",
        meta={"modules": modules, "available_count": available_count},
    )


def get_runtime_capabilities() -> dict:
    """
    Unified runtime capability map.

    Returns a stable JSON-serializable dict with all detected capabilities.
    Every detection is fail-open — missing capabilities produce
    {available: False} entries, never exceptions.

    Schema (always present):
        {
            "timestamp": float,
            "capabilities": {
                "python": {...},
                "packages": {...},
                "tools": {...},
                "filesystem": {...},
                "network": {...},
                "docker": {...},
                "git": {...},
                "optional_modules": {...},
            },
            "summary": {
                "total": int,
                "available": int,
                "unavailable": int,
            }
        }
    """
    detectors = [
        _detect_python,
        _detect_packages,
        _detect_tools,
        _detect_filesystem,
        _detect_network,
        _detect_docker,
        _detect_git,
        _detect_optional_modules,
    ]

    capabilities: dict[str, dict] = {}
    for detector in detectors:
        try:
            cap = detector()
            capabilities[cap.name] = cap.to_dict()
        except Exception as e:
            name = detector.__name__.replace("_detect_", "")
            capabilities[name] = Capability(
                name=name, detail=f"detector crashed: {str(e)[:100]}"
            ).to_dict()

    available = sum(1 for c in capabilities.values() if c.get("available"))
    total = len(capabilities)

    result = {
        "timestamp": time.time(),
        "capabilities": capabilities,
        "summary": {
            "total": total,
            "available": available,
            "unavailable": total - available,
        },
    }

    try:
        log.info("runtime_capabilities_detected",
                 available=available, total=total)
    except Exception:
        _silent_log.debug("suppressed_exception", src='runtime_introspection.py')

    return result


# ═══════════════════════════════════════════════════════════════
# PRIORITY 2 — TOOL HEALTH CHECK LAYER
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolHealth:
    """Health check result for a single tool.

    Attributes:
        tool: Tool name.
        status: "ok" | "degraded" | "unavailable".
        reason: Human-readable explanation.
        response_ms: Time to check, in milliseconds.
        dependencies_met: Whether all required deps are available.
    """
    tool:             str
    status:           str  = "unavailable"  # ok | degraded | unavailable
    reason:           str  = ""
    response_ms:      int  = 0
    dependencies_met: bool = False

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "status": self.status,
            "reason": self.reason,
            "response_ms": self.response_ms,
            "dependencies_met": self.dependencies_met,
        }


# Tool → required dependencies (module names that must be importable)
_TOOL_DEPENDENCIES: dict[str, list[str]] = {
    "read_file":       [],
    "write_file":      [],
    "list_directory":  [],
    "search_in_files": [],
    "git_status":      [],  # git binary, not a Python module
    "git_diff":        [],
    "git_commit":      [],
    "run_tests":       [],  # pytest may or may not be available
    "docker_ps":       [],
    "docker_logs":     [],
    "fetch_url":       ["requests"],
    "web_search":      ["requests"],
    "memory_store_solution":  ["qdrant_client"],
    "memory_search_similar":  ["qdrant_client"],
    "api_healthcheck":        ["requests"],
    "http_post_json":         ["requests"],
}

# Tool → callable check function
_TOOL_CHECKS: dict[str, callable] = {}


def _check_deps(tool_name: str) -> tuple[bool, str]:
    """Check if all dependencies for a tool are available."""
    deps = _TOOL_DEPENDENCIES.get(tool_name, [])
    if not deps:
        return True, "no dependencies required"
    missing = []
    for dep in deps:
        try:
            importlib.import_module(dep)
        except ImportError:
            missing.append(dep)
    if missing:
        return False, f"missing: {', '.join(missing)}"
    return True, "all dependencies available"


def _check_binary(name: str, timeout: int = 3) -> tuple[bool, str]:
    """Check if a binary is available on PATH."""
    try:
        result = subprocess.run(  # nosec B603 B607
            [name, "--version"], capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()[:80]
    except FileNotFoundError:
        return False, f"{name} binary not found"
    except subprocess.TimeoutExpired:
        return False, f"{name} timed out"
    except Exception as e:
        return False, str(e)[:80]


def check_tool_health(tool_name: str) -> ToolHealth:
    """
    Check the health of a specific tool.

    Returns ToolHealth with status: ok | degraded | unavailable.
    Never raises — returns unavailable status on any error.

    Checks:
    1. Dependency availability (Python modules)
    2. Binary availability (for git, docker, etc.)
    3. Timeout detection (degraded if slow)
    """
    t0 = time.monotonic()
    try:
        # Check dependencies
        deps_ok, deps_detail = _check_deps(tool_name)
        ms = int((time.monotonic() - t0) * 1000)

        if not deps_ok:
            return ToolHealth(
                tool=tool_name,
                status="unavailable",
                reason=f"dependency check failed: {deps_detail}",
                response_ms=ms,
                dependencies_met=False,
            )

        # Special checks for binary-dependent tools
        if tool_name.startswith("git_"):
            git_ok, git_detail = _check_binary("git")
            ms = int((time.monotonic() - t0) * 1000)
            if not git_ok:
                return ToolHealth(
                    tool=tool_name,
                    status="unavailable",
                    reason=f"git binary: {git_detail}",
                    response_ms=ms,
                    dependencies_met=False,
                )

        if tool_name.startswith("docker_"):
            docker_ok, docker_detail = _check_binary("docker")
            ms = int((time.monotonic() - t0) * 1000)
            if not docker_ok:
                return ToolHealth(
                    tool=tool_name,
                    status="unavailable",
                    reason=f"docker: {docker_detail}",
                    response_ms=ms,
                    dependencies_met=False,
                )

        # Check for pytest availability (test tools)
        if tool_name in ("run_tests", "run_unit_tests", "run_smoke_tests"):
            try:
                importlib.import_module("pytest")
            except ImportError:
                ms = int((time.monotonic() - t0) * 1000)
                return ToolHealth(
                    tool=tool_name,
                    status="degraded",
                    reason="pytest not installed — test tools limited",
                    response_ms=ms,
                    dependencies_met=False,
                )

        ms = int((time.monotonic() - t0) * 1000)

        # Slow check detection
        if ms > 2000:
            return ToolHealth(
                tool=tool_name,
                status="degraded",
                reason=f"health check slow ({ms}ms)",
                response_ms=ms,
                dependencies_met=deps_ok,
            )

        return ToolHealth(
            tool=tool_name,
            status="ok",
            reason="all checks passed",
            response_ms=ms,
            dependencies_met=deps_ok,
        )

    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return ToolHealth(
            tool=tool_name,
            status="unavailable",
            reason=f"health check failed: {str(e)[:150]}",
            response_ms=ms,
        )


def check_all_tools_health() -> dict[str, dict]:
    """
    Run health checks on all known tools.
    Returns {tool_name: ToolHealth.to_dict()}.
    """
    results = {}
    for tool_name in sorted(_TOOL_DEPENDENCIES.keys()):
        results[tool_name] = check_tool_health(tool_name).to_dict()
    return results


# ═══════════════════════════════════════════════════════════════
# PRIORITY 3 — ENHANCED ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

# Extended category mapping (superset of observability_helpers)
_ERROR_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "network_error":    (ConnectionError, ConnectionRefusedError, ConnectionResetError),
    "timeout_error":    (TimeoutError,),
    "auth_error":       (PermissionError,),
    "dependency_error": (ImportError, ModuleNotFoundError),
    "file_error":       (FileNotFoundError, FileExistsError, IsADirectoryError),
    "type_error":       (TypeError, ValueError, AttributeError),
    "memory_error":     (MemoryError,),
    "runtime_error":    (RuntimeError,),
    "assertion_error":  (AssertionError,),
    "os_error":         (OSError,),
}

_ERROR_KEYWORD_MAP: dict[str, list[str]] = {
    "network_error":    ["connection refused", "connection reset", "unreachable",
                         "network", "socket", "dns", "resolve"],
    "timeout_error":    ["timeout", "timed out", "deadline exceeded"],
    "auth_error":       ["unauthorized", "forbidden", "403", "401", "auth",
                         "token expired", "credentials", "permission denied"],
    "dependency_error": ["no module named", "import error", "cannot import",
                         "missing dependency", "not installed"],
    "quota_error":      ["rate limit", "too many requests", "429", "quota exceeded",
                         "throttled"],
    "server_error":     ["500", "502", "503", "504", "internal server error",
                         "bad gateway", "service unavailable"],
    "oom_error":        ["out of memory", "oom", "killed", "cannot allocate"],
    "syntax_error":     ["syntax error", "unexpected token", "invalid syntax",
                         "parsing error"],
    "config_error":     ["missing config", "invalid config", "environment variable",
                         "not configured", "no such setting"],
}


def classify_error(error: BaseException) -> dict:
    """
    Enhanced error classification with consistent category names.

    Returns:
        {
            "category": str,       # e.g. "network_error", "timeout_error"
            "type": str,           # exception class name
            "message": str,        # truncated error message
            "retryable": bool,     # safe to retry
            "severity": str,       # "low" | "medium" | "high" | "critical"
            "suggestion": str,     # brief remediation hint
        }

    Categories:
        network_error, timeout_error, auth_error, dependency_error,
        file_error, type_error, quota_error, server_error,
        oom_error, syntax_error, config_error, memory_error,
        runtime_error, assertion_error, os_error, unknown_error

    Never raises — always returns a valid classification.
    """
    try:
        error_type = type(error).__name__
        message = str(error)[:300]
        msg_lower = message.lower()

        # 1. Check by exception type
        for category, types in _ERROR_TYPE_MAP.items():
            if isinstance(error, types):
                return _build_classification(category, error_type, message)

        # 2. Check by message keywords
        for category, keywords in _ERROR_KEYWORD_MAP.items():
            if any(kw in msg_lower for kw in keywords):
                return _build_classification(category, error_type, message)

        # 3. Unknown
        return _build_classification("unknown_error", error_type, message)

    except Exception:
        return {
            "category": "unknown_error",
            "type": "Exception",
            "message": str(error)[:300] if error else "unknown",
            "retryable": False,
            "severity": "medium",
            "suggestion": "Inspect error details manually.",
        }


_RETRYABLE_CATEGORIES = frozenset({
    "network_error", "timeout_error", "quota_error", "server_error",
})

_SEVERITY_MAP: dict[str, str] = {
    "network_error":    "medium",
    "timeout_error":    "medium",
    "auth_error":       "high",
    "dependency_error": "high",
    "file_error":       "low",
    "type_error":       "medium",
    "quota_error":      "low",
    "server_error":     "medium",
    "oom_error":        "critical",
    "syntax_error":     "medium",
    "config_error":     "high",
    "memory_error":     "critical",
    "runtime_error":    "medium",
    "assertion_error":  "medium",
    "os_error":         "medium",
    "unknown_error":    "medium",
}

_SUGGESTION_MAP: dict[str, str] = {
    "network_error":    "Check network connectivity and DNS resolution.",
    "timeout_error":    "Increase timeout or retry with backoff.",
    "auth_error":       "Verify API keys and credentials in environment variables.",
    "dependency_error": "Install missing package: pip install <package>.",
    "file_error":       "Check file path and permissions.",
    "type_error":       "Review function arguments and types.",
    "quota_error":      "Wait and retry, or switch to a different provider.",
    "server_error":     "Retry with backoff. Check upstream service status.",
    "oom_error":        "Reduce batch size or memory usage. Check for leaks.",
    "syntax_error":     "Fix the syntax error in the source code.",
    "config_error":     "Review configuration files and environment variables.",
    "memory_error":     "Reduce memory usage. Consider chunked processing.",
    "runtime_error":    "Review the logic that caused this error.",
    "assertion_error":  "Check the assertion condition.",
    "os_error":         "Check OS-level resources and permissions.",
    "unknown_error":    "Inspect error details manually.",
}


def _build_classification(category: str, error_type: str, message: str) -> dict:
    """Build a structured error classification dict."""
    return {
        "category":   category,
        "type":       error_type,
        "message":    message,
        "retryable":  category in _RETRYABLE_CATEGORIES,
        "severity":   _SEVERITY_MAP.get(category, "medium"),
        "suggestion": _SUGGESTION_MAP.get(category, "Inspect error details manually."),
    }


# ═══════════════════════════════════════════════════════════════
# PRIORITY 4 — EXECUTION SIGNAL RECORDING
# ═══════════════════════════════════════════════════════════════

@dataclass
class ExecutionSignal:
    """A recorded execution signal for future planning use.

    These signals are passive — they record what happened but
    do NOT influence any current behavior.
    """
    signal_type: str        # "duration_bucket" | "retry_frequency" | "tool_failure"
    source:      str        # e.g. "circuit_breaker:ollama", "retry:api_call"
    value:       Any = None # signal-specific value
    timestamp:   float = 0.0
    meta:        dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal_type,
            "source": self.source,
            "value": self.value,
            "timestamp": self.timestamp,
            "meta": self.meta,
        }


# In-memory signal buffer (bounded, no persistence)
_SIGNAL_BUFFER: list[dict] = []
_MAX_SIGNALS = 500


def record_execution_signal(
    signal_type: str,
    source: str,
    value: Any = None,
    **meta,
) -> None:
    """
    Record a passive execution signal.

    Signal types:
    - "duration_bucket": Execution time category (fast/normal/slow/timeout)
    - "retry_frequency": How often retries happen for a source
    - "tool_failure": Tool failure occurrence

    These signals are stored in memory only (no persistence).
    They do NOT influence any behavior — purely observational.
    """
    try:
        signal = {
            "signal_type": signal_type,
            "source": source,
            "value": value,
            "timestamp": time.time(),
            "meta": meta,
        }
        _SIGNAL_BUFFER.append(signal)
        # Bounded buffer — drop oldest when full
        if len(_SIGNAL_BUFFER) > _MAX_SIGNALS:
            del _SIGNAL_BUFFER[:_MAX_SIGNALS // 5]  # drop 20%
    except Exception:
        pass  # signal recording must never crash anything


def get_execution_signals(
    signal_type: Optional[str] = None,
    source: Optional[str] = None,
    last_n: int = 50,
) -> list[dict]:
    """
    Retrieve recorded execution signals.

    Args:
        signal_type: Filter by type (optional).
        source: Filter by source (optional).
        last_n: Maximum number of signals to return.

    Returns list of signal dicts, most recent first.
    """
    try:
        signals = _SIGNAL_BUFFER[:]
        if signal_type:
            signals = [s for s in signals if s.get("signal_type") == signal_type]
        if source:
            signals = [s for s in signals if s.get("source") == source]
        return signals[-last_n:][::-1]  # most recent first
    except Exception:
        return []


def get_signal_summary() -> dict:
    """
    Aggregate summary of all recorded execution signals.

    Returns:
        {
            "total_signals": int,
            "by_type": {signal_type: count},
            "by_source": {source: count},
            "duration_buckets": {fast: N, normal: N, slow: N, timeout: N},
            "retry_sources": [source, ...],
            "tool_failures": [source, ...],
        }
    """
    try:
        from collections import Counter
        by_type = Counter(s.get("signal_type") for s in _SIGNAL_BUFFER)
        by_source = Counter(s.get("source") for s in _SIGNAL_BUFFER)

        duration_buckets = Counter(
            s.get("value")
            for s in _SIGNAL_BUFFER
            if s.get("signal_type") == "duration_bucket"
        )

        retry_sources = list(set(
            s.get("source")
            for s in _SIGNAL_BUFFER
            if s.get("signal_type") == "retry_frequency"
        ))

        tool_failures = list(set(
            s.get("source")
            for s in _SIGNAL_BUFFER
            if s.get("signal_type") == "tool_failure"
        ))

        return {
            "total_signals": len(_SIGNAL_BUFFER),
            "by_type": dict(by_type),
            "by_source": dict(by_source.most_common(20)),
            "duration_buckets": dict(duration_buckets),
            "retry_sources": retry_sources[:20],
            "tool_failures": tool_failures[:20],
        }
    except Exception:
        return {"total_signals": len(_SIGNAL_BUFFER)}


def clear_signals() -> None:
    """Clear all recorded signals (for testing)."""
    _SIGNAL_BUFFER.clear()


# ── Convenience: duration bucketing ───────────────────────────

def duration_bucket(ms: int) -> str:
    """Classify execution duration into a bucket.

    Returns: "fast" (<100ms), "normal" (100-1000ms), "slow" (1-10s), "timeout" (>10s).
    """
    if ms < 100:
        return "fast"
    elif ms < 1000:
        return "normal"
    elif ms < 10000:
        return "slow"
    else:
        return "timeout"
