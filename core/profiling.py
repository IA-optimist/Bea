"""
core/profiling.py — Lightweight profiling instrumentation for JarvisMax.

Goals :
- Tag critical paths with minimal overhead (single perf_counter() per call)
- Emit metrics via Prometheus (if prometheus_client available) AND structlog
- Context manager + decorator APIs
- Zero runtime cost when disabled (env var JARVIS_PROFILING=0)

Usage :
    from core.profiling import profile_span, profile_fn

    # Context manager
    with profile_span("mission.plan"):
        plan = planner.build_plan(...)

    # Decorator (sync or async)
    @profile_fn("llm.call")
    async def call_llm(...):
        ...

Observability :
    - Histogram `jarvis_profile_duration_seconds{span=...}` (Prometheus)
    - structlog "profile.span" event with name, duration_ms, status
"""
from __future__ import annotations

import asyncio
import functools
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

import structlog

log = structlog.get_logger(__name__)

# ── Config ───────────────────────────────────────────────────
_ENABLED = os.getenv("JARVIS_PROFILING", "1") != "0"
_SLOW_THRESHOLD_MS = float(os.getenv("JARVIS_PROFILE_SLOW_MS", "500"))

# ── Prometheus histogram (lazy init) ─────────────────────────
_histogram = None
_histogram_init_tried = False


def _get_histogram():
    """Lazy-init Prometheus histogram — None if prometheus_client absent."""
    global _histogram, _histogram_init_tried
    if _histogram_init_tried:
        return _histogram
    _histogram_init_tried = True
    try:
        from prometheus_client import Histogram
        _histogram = Histogram(
            "jarvis_profile_duration_seconds",
            "Duration of profiled spans, by name",
            ["span", "status"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        )
    except Exception as e:
        log.debug("profiling.prometheus_unavailable", err=str(e)[:60])
        _histogram = None
    return _histogram


# ── Context manager ──────────────────────────────────────────
@contextmanager
def profile_span(name: str, **extra: Any) -> Iterator[None]:
    """
    Measure the duration of a code block.

    Args:
        name: Span name (e.g. "mission.plan", "llm.call", "db.query")
        **extra: Additional fields to log (e.g. model="gpt-4")
    """
    if not _ENABLED:
        yield
        return

    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration_s = time.perf_counter() - start
        duration_ms = duration_s * 1000.0

        # Prometheus
        hist = _get_histogram()
        if hist is not None:
            try:
                hist.labels(span=name, status=status).observe(duration_s)
            except Exception:
                pass

        # Structlog : always DEBUG, WARN if slow
        payload = {"name": name, "duration_ms": round(duration_ms, 1), "status": status, **extra}
        if duration_ms > _SLOW_THRESHOLD_MS:
            log.warning("profile.slow_span", **payload)
        else:
            log.debug("profile.span", **payload)


# ── Decorator (sync + async) ─────────────────────────────────
def profile_fn(name: Optional[str] = None) -> Callable:
    """
    Decorator — profile a sync or async function.

    If `name` is None, uses `<module>.<func_name>`.
    """
    def decorator(fn: Callable) -> Callable:
        span_name = name or f"{fn.__module__}.{fn.__name__}"

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with profile_span(span_name):
                    return await fn(*args, **kwargs)
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with profile_span(span_name):
                return fn(*args, **kwargs)
        return sync_wrapper

    return decorator


# ── On-demand cProfile helper (for deep investigation) ───────
def cprofile_block(output_path: str):
    """
    Context manager that writes a cProfile dump for the enclosed block.

    Use sparingly — cProfile overhead is significant. Only for diagnostic runs.

    Example :
        with cprofile_block("/tmp/mission_run.prof"):
            orchestrator.run_mission(goal)
        # Inspect with : python -m pstats /tmp/mission_run.prof
    """
    @contextmanager
    def _cm():
        import cProfile
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            yield
        finally:
            profiler.disable()
            profiler.dump_stats(output_path)
            log.info("profile.cprofile_written", path=output_path)
    return _cm()
