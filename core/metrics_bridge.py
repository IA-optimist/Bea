"""
JARVIS MAX — Metrics Bridge
==============================
Non-invasive instrumentation layer that connects runtime components
to the metrics store and trace intelligence.

Instead of modifying CRITICAL files (meta_orchestrator, tool_executor,
llm_factory), this module:

1. MONKEY-PATCHES: Wraps key methods with instrumented versions at import time
2. TRACE→METRICS: Converts trace events to metric increments automatically
3. COST TRACKING: Parses OpenRouter response metadata for real costs
4. SNAPSHOT PERSISTENCE: Periodic atomic writes of metrics to disk
5. ALERT CONDITIONS: Evaluates thresholds and emits alert events

Usage:
    # Call once at startup (in api/main.py or main.py)
    from core.metrics_bridge import install_instrumentation
    install_instrumentation()

Design:
    - All patches are fail-open (wrapped in try/except)
    - Original function behavior is NEVER altered
    - If metrics_store fails, the runtime continues unaffected
    - Thread-safe via metrics_store's internal locking
"""
from __future__ import annotations

import structlog
log = structlog.get_logger(__name__)

import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import structlog
    log = structlog.get_logger(__name__)
except ImportError:
    log = structlog.get_logger(__name__)


_INSTALLED = False
_INSTALL_LOCK = threading.Lock()


# ═══════════════════════════════════════════════════════════════
# 1. MONKEY-PATCH INSTRUMENTATION
# ═══════════════════════════════════════════════════════════════

def _patch_meta_orchestrator() -> bool:
    """Instrument MetaOrchestrator.run_mission with metrics."""
    try:
        from core.meta_orchestrator import MetaOrchestrator
        original = MetaOrchestrator.run_mission

        @functools.wraps(original)
        async def instrumented_run_mission(self, goal, mode="auto", mission_id=None,
                                           callback=None, use_budget=False):
            from core.metrics_store import (
                emit_mission_submitted, emit_mission_completed,
                emit_mission_failed, emit_mission_timeout,
                get_metrics,
            )

            # Classify mission type from mode/goal
            mission_type = mode or "auto"
            emit_mission_submitted(mission_type)
            get_metrics().set_gauge("missions_active", 
                sum(1 for c in self._missions.values() 
                    if hasattr(c, 'status') and c.status.value in ("PLANNED", "RUNNING", "REVIEW")))

            t0 = time.monotonic()
            try:
                ctx = await original(self, goal, mode, mission_id, callback, use_budget)
                duration_ms = (time.monotonic() - t0) * 1000

                if ctx.status.value == "DONE":
                    emit_mission_completed(mission_type, duration_ms)
                elif ctx.status.value == "FAILED":
                    if ctx.error and "timeout" in ctx.error.lower():
                        emit_mission_timeout(mission_type)
                    else:
                        emit_mission_failed(mission_type, ctx.error or "unknown")

                # Update active gauge
                get_metrics().set_gauge("missions_active",
                    sum(1 for c in self._missions.values()
                        if hasattr(c, 'status') and c.status.value in ("PLANNED", "RUNNING", "REVIEW")))

                return ctx
            except Exception as e:
                duration_ms = (time.monotonic() - t0) * 1000
                emit_mission_failed(mission_type, str(e)[:200])
                raise

        MetaOrchestrator.run_mission = instrumented_run_mission
        log.info("metrics_bridge.patched", target="MetaOrchestrator.run_mission")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="MetaOrchestrator", err=str(e)[:80])
        return False


def _patch_tool_executor() -> bool:
    """Instrument ToolExecutor.execute and _execute_with_retry with metrics."""
    try:
        from core.tool_executor import ToolExecutor
        original_execute = ToolExecutor.execute
        original_retry = ToolExecutor._execute_with_retry

        @functools.wraps(original_execute)
        def instrumented_execute(self, tool_name, params, approval_mode="SUPERVISED"):
            from core.metrics_store import (
                emit_tool_invocation, emit_tool_timeout, get_metrics,
            )

            result = original_execute(self, tool_name, params, approval_mode)

            try:
                success = bool(result.get("ok"))
                duration = result.get("duration_ms", 0)
                emit_tool_invocation(tool_name, success, duration)

                if not success:
                    error = result.get("error", "")
                    if "timeout" in str(error).lower():
                        emit_tool_timeout(tool_name)
                    if result.get("blocked_by_policy"):
                        get_metrics().inc("tool_blocked_by_policy_total",
                                          labels={"tool": tool_name})

                # Update executor gauges
                get_metrics().set_gauge("executor_active_tasks",
                    len([1 for t in getattr(self, '_tools', {})]))
            except Exception as _exc:
                log.warning("swallowed_exception", action="executor_gauge_update", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

            return result

        @functools.wraps(original_retry)
        def instrumented_retry(self, tool_name, params, max_retries=1):
            from core.metrics_store import emit_retry
            result = original_retry(self, tool_name, params, max_retries)
            try:
                # If the result has retry indicators
                if max_retries > 0 and not result.get("ok"):
                    emit_retry("tool_executor")
            except Exception as _exc:
                log.warning("swallowed_exception", action="executor_retry_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return result

        ToolExecutor.execute = instrumented_execute
        ToolExecutor._execute_with_retry = instrumented_retry
        log.info("metrics_bridge.patched", target="ToolExecutor.execute")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="ToolExecutor", err=str(e)[:80])
        return False


def _patch_llm_factory() -> bool:
    """Instrument LLMFactory.get and safe_invoke with model routing metrics."""
    try:
        from core.llm_factory import LLMFactory
        original_get = LLMFactory.get
        original_invoke = LLMFactory.safe_invoke

        @functools.wraps(original_get)
        def instrumented_get(self, role="default", **kwargs):
            from core.metrics_store import emit_model_selected
            llm = original_get(self, role, **kwargs)
            try:
                provider = getattr(llm, "_jarvis_provider", "unknown")
                model_name = getattr(llm, "model_name", getattr(llm, "model", provider))
                locality = "local" if provider == "ollama" else "cloud"
                emit_model_selected(model_name, locality)
            except Exception as _exc:
                log.warning("swallowed_exception", action="model_selected_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return llm

        @functools.wraps(original_invoke)
        async def instrumented_invoke(self, messages, role="fast", timeout=60.0,
                                       session_id="", agent_name="", **kwargs):
            from core.metrics_store import (
                emit_model_latency, emit_model_failure,
            )

            t0 = time.monotonic()
            try:
                resp = await original_invoke(self, messages, role, timeout,
                                              session_id, agent_name, **kwargs)
                ms = (time.monotonic() - t0) * 1000

                # Extract model info from response
                try:
                    model_name = "unknown"
                    if hasattr(resp, "response_metadata"):
                        meta = resp.response_metadata or {}
                        model_name = meta.get("model", model_name)
                        # OpenRouter cost extraction
                        _extract_cost_from_response(meta, model_name,
                                                     kwargs.get("mission_id", ""))
                    emit_model_latency(model_name, ms)
                except Exception as _exc:
                    log.warning("swallowed_exception", action="model_latency_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

                return resp
            except Exception as e:
                ms = (time.monotonic() - t0) * 1000
                try:
                    emit_model_failure(role, str(e)[:200])
                except Exception as _exc:
                    log.warning("swallowed_exception", action="model_failure_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                raise

        LLMFactory.get = instrumented_get
        LLMFactory.safe_invoke = instrumented_invoke
        log.info("metrics_bridge.patched", target="LLMFactory.get/safe_invoke")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="LLMFactory", err=str(e)[:80])
        return False


def _patch_memory_facade() -> bool:
    """Instrument MemoryFacade.store and .search with memory metrics."""
    try:
        from core.memory_facade import MemoryFacade
        original_store = MemoryFacade.store
        original_search = MemoryFacade.search

        @functools.wraps(original_store)
        def instrumented_store(self, content, content_type="general",
                                tags=None, metadata=None):
            from core.metrics_store import get_metrics
            result = original_store(self, content, content_type, tags, metadata)
            try:
                m = get_metrics()
                m.inc("memory_entries_total", labels={"type": content_type})
                if result.get("ok"):
                    m.set_gauge("memory_persistence_ok", 1)
                else:
                    m.set_gauge("memory_persistence_ok", 0)
            except Exception as _exc:
                log.warning("swallowed_exception", action="memory_persistence_gauge", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return result

        @functools.wraps(original_search)
        def instrumented_search(self, query, content_type=None, top_k=5):
            from core.metrics_store import emit_memory_search
            t0 = time.monotonic()
            results = original_search(self, query, content_type, top_k)
            try:
                ms = (time.monotonic() - t0) * 1000
                hit = len(results) > 0
                emit_memory_search(hit, ms)
            except Exception as _exc:
                log.warning("swallowed_exception", action="memory_search_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return results

        MemoryFacade.store = instrumented_store
        MemoryFacade.search = instrumented_search
        log.info("metrics_bridge.patched", target="MemoryFacade.store/search")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="MemoryFacade", err=str(e)[:80])
        return False


def _patch_improvement_loop() -> bool:
    """Instrument ImprovementLoop.run_experiment with improvement metrics."""
    try:
        from core.improvement_loop import ImprovementLoop
        original = ImprovementLoop.run_experiment

        @functools.wraps(original)
        def instrumented_run_experiment(self, spec, apply_patch=None):
            from core.metrics_store import emit_experiment, get_metrics
            report = original(self, spec, apply_patch)
            try:
                score_delta = report.evaluation.get("composite", 0) if isinstance(
                    report.evaluation, dict) else 0
                emit_experiment(report.decision, score_delta)
                if report.decision == "rejected" and "regression" in report.reason.lower():
                    get_metrics().inc("regressions_blocked_total")
                if report.decision in ("error", "rejected"):
                    get_metrics().inc("rollback_total")
            except Exception as _exc:
                log.warning("swallowed_exception", action="regressions_blocked_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
            return report

        ImprovementLoop.run_experiment = instrumented_run_experiment
        log.info("metrics_bridge.patched", target="ImprovementLoop.run_experiment")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="ImprovementLoop", err=str(e)[:80])
        return False


# ═══════════════════════════════════════════════════════════════
# 2. TRACE → METRICS BRIDGE
# ═══════════════════════════════════════════════════════════════

# Map trace event names to metric emitter calls
_TRACE_EVENT_MAP: dict[str, Callable] = {}


def _init_trace_event_map():
    """Lazy init the trace event map (imports metrics_store)."""
    global _TRACE_EVENT_MAP
    if _TRACE_EVENT_MAP:
        return
    from core.metrics_store import (
        emit_tool_invocation, emit_tool_timeout,
        emit_model_failure, emit_mission_failed,
        emit_mission_timeout, emit_retry, get_metrics,
    )
    _TRACE_EVENT_MAP = {
        "tool_failed":        lambda e: (emit_tool_invocation(e.get("tool", "unknown"), False, e.get("duration_ms", 0)),
                                          get_metrics().record_failure("tool_crash", "tool_executor",
                                                                       e.get("error", "unknown"),
                                                                       tool_name=e.get("tool", ""))),
        "tool_timeout":       lambda e: emit_tool_timeout(e.get("tool", "unknown")),
        "tool_executed":      lambda e: None if e.get("ok") is not False else
                                         emit_tool_invocation(e.get("tool", "unknown"), False, e.get("duration_ms", 0)),
        "model_error":        lambda e: emit_model_failure(e.get("model_id", "unknown"), e.get("error", "")),
        "mission_failed":     lambda e: emit_mission_failed(e.get("type", "unknown"), e.get("error", "")),
        "execution_timeout":  lambda e: emit_mission_timeout(e.get("type", "unknown")),
        "retry_attempt":      lambda e: emit_retry(e.get("component", "executor")),
        "circuit_breaker":    lambda e: (get_metrics().inc("circuit_breaker_open_total")
                                          if e.get("state") == "open" else None),
    }


def process_trace_event(event: dict) -> None:
    """
    Process a single trace event and emit corresponding metrics.

    Called from MissionTrace.record() after patching, or manually
    from any component that generates trace events.

    Fail-open: never raises.
    """
    try:
        _init_trace_event_map()
        event_name = event.get("event", "")
        handler = _TRACE_EVENT_MAP.get(event_name)
        if handler:
            handler(event)
    except Exception as _exc:
        log.warning("swallowed_exception", action="trace_event_dispatch", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


def _patch_trace() -> bool:
    """Instrument MissionTrace.record to auto-process events."""
    try:
        from core.trace import MissionTrace
        original_record = MissionTrace.record

        @functools.wraps(original_record)
        def instrumented_record(self, component, event, **data):
            original_record(self, component, event, **data)
            try:
                process_trace_event({"component": component, "event": event, **data})
            except Exception as _exc:
                log.warning("swallowed_exception", action="trace_record_wrap", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        MissionTrace.record = instrumented_record
        log.info("metrics_bridge.patched", target="MissionTrace.record")
        return True
    except Exception as e:
        log.debug("metrics_bridge.patch_failed", target="MissionTrace", err=str(e)[:80])
        return False


# ═══════════════════════════════════════════════════════════════
# 3. REAL COST TRACKING
# ═══════════════════════════════════════════════════════════════

def _extract_cost_from_response(response_metadata: dict, model_id: str,
                                 mission_id: str = "") -> None:
    """
    Extract real cost from OpenRouter response headers.

    OpenRouter includes cost info in response_metadata:
      - x-openrouter-cost (or nested in token_usage)
      - model (actual model used, may differ from requested)

    Falls back to estimated cost tiers if real cost unavailable.
    """
    try:
        from core.metrics_store import get_metrics

        actual_cost = None
        actual_model = model_id

        # Try OpenRouter-specific headers
        headers = response_metadata.get("headers", {})
        if isinstance(headers, dict):
            cost_str = headers.get("x-openrouter-cost", "")
            if cost_str:
                actual_cost = float(cost_str)
            actual_model = headers.get("x-openrouter-model", actual_model)

        # Try token_usage for cost
        usage = response_metadata.get("token_usage", {})
        if not actual_cost and usage:
            # OpenRouter sometimes puts cost in usage
            actual_cost = usage.get("cost")
            if actual_cost is not None:
                actual_cost = float(actual_cost)

        # Record tokens for estimation if no real cost
        total_tokens = 0
        if usage:
            total_tokens = (usage.get("prompt_tokens", 0) +
                            usage.get("completion_tokens", 0))

        # Determine cost tier from model name
        tier = "standard"
        model_lower = actual_model.lower()
        if "ollama" in model_lower or "local" in model_lower:
            tier = "local"
        elif "nano" in model_lower or "mini" in model_lower or "flash-lite" in model_lower:
            tier = "nano"
        elif "flash" in model_lower or "deepseek" in model_lower:
            tier = "cheap"
        elif "opus" in model_lower or "gpt-4.5" in model_lower:
            tier = "premium"

        get_metrics().record_cost(
            actual_model, total_tokens, tier,
            mission_id=mission_id,
            actual_cost=actual_cost,
        )

    except Exception as _exc:
        log.warning("swallowed_exception", action="mission_cost_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


# ═══════════════════════════════════════════════════════════════
# 4. SNAPSHOT PERSISTENCE
# ═══════════════════════════════════════════════════════════════

_SNAPSHOT_INTERVAL = 60  # seconds
_snapshot_thread: threading.Thread | None = None
_snapshot_stop = threading.Event()


def _snapshot_loop(path: Path):
    """Background thread that writes metric snapshots atomically."""
    cycle = 0
    while not _snapshot_stop.wait(_SNAPSHOT_INTERVAL):
        try:
            from core.metrics_store import get_metrics
            data = get_metrics().snapshot()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(str(tmp), str(path))
        except Exception as e:
            try:
                log.debug("snapshot_write_failed", err=str(e)[:80])
            except Exception as _exc:
                log.warning("swallowed_exception", action="snapshot_write_log", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        # Save kernel performance every 5 cycles (~5 min at default interval)
        cycle += 1
        if cycle % 5 == 0:
            try:
                from kernel.runtime.boot import save_performance
                save_performance()
            except Exception as _exc:
                log.warning("swallowed_exception", action="save_performance_call", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])


def start_snapshot_persistence(workspace_dir: str = "workspace") -> None:
    """Start the background snapshot writer."""
    global _snapshot_thread
    if _snapshot_thread and _snapshot_thread.is_alive():
        return
    path = Path(workspace_dir) / "metrics_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _snapshot_stop.clear()
    _snapshot_thread = threading.Thread(target=_snapshot_loop, args=(path,),
                                        daemon=True, name="metrics-snapshot")
    _snapshot_thread.start()
    log.info("metrics_snapshot.started", path=str(path), interval_s=_SNAPSHOT_INTERVAL)


def stop_snapshot_persistence() -> None:
    """Stop the background snapshot writer."""
    _snapshot_stop.set()
    if _snapshot_thread:
        _snapshot_thread.join(timeout=5)


# ═══════════════════════════════════════════════════════════════
# 5. ALERT CONDITIONS
# ═══════════════════════════════════════════════════════════════

@functools.lru_cache(maxsize=1)
def _default_thresholds() -> dict[str, Any]:
    return {
        "mission_success_rate_min": 0.7,
        "tool_failure_rate_max": 0.3,
        "retry_attempts_max": 5,
        "circuit_breaker_opens_per_hour_max": 3,
    }


def evaluate_alerts(window_s: float = 3600) -> list[dict]:
    """
    Evaluate alert conditions against current metrics.

    Returns list of triggered alerts with severity and recommendation.
    Each alert is emitted as a metric increment (alert_triggered_total).
    """
    try:
        from core.metrics_store import get_metrics
        m = get_metrics()
        thresholds = _default_thresholds()
        alerts: list[dict] = []

        # 1. Mission success rate
        submitted = m.get_counter_total("missions_submitted_total")
        completed = m.get_counter_total("missions_completed_total")
        if submitted >= 5:
            rate = completed / submitted
            if rate < thresholds["mission_success_rate_min"]:
                alerts.append({
                    "alert": "low_mission_success_rate",
                    "severity": "warning" if rate >= 0.5 else "critical",
                    "current": round(rate, 3),
                    "threshold": thresholds["mission_success_rate_min"],
                    "recommendation": "Check failure patterns; consider increasing retries or fallbacks",
                })

        # 2. Tool failure rate
        tool_total = m.get_counter_total("tool_invocations_total")
        tool_fail = m.get_counter_total("tool_failures_total")
        if tool_total >= 10:
            fail_rate = tool_fail / tool_total
            if fail_rate > thresholds["tool_failure_rate_max"]:
                # Find worst tool
                worst_tool = "unknown"
                worst_rate = 0
                tool_counter = m._counters.get("tool_failures_total")
                if tool_counter:
                    for lk, v in tool_counter.get_all().items():
                        if v > worst_rate:
                            worst_rate = v
                            worst_tool = lk
                alerts.append({
                    "alert": "high_tool_failure_rate",
                    "severity": "warning",
                    "current": round(fail_rate, 3),
                    "threshold": thresholds["tool_failure_rate_max"],
                    "worst_tool": worst_tool,
                    "recommendation": f"Check tool health; consider deprioritizing {worst_tool}",
                })

        # 3. Retry storm
        retries = m.get_counter_total("retry_attempts_total")
        if retries > thresholds["retry_attempts_max"]:
            alerts.append({
                "alert": "retry_storm",
                "severity": "warning" if retries < 15 else "critical",
                "current": int(retries),
                "threshold": thresholds["retry_attempts_max"],
                "recommendation": "Check provider health and network connectivity",
            })

        # 4. Circuit breaker flapping
        cb_opens = m.get_counter_total("circuit_breaker_open_total")
        if cb_opens > thresholds["circuit_breaker_opens_per_hour_max"]:
            alerts.append({
                "alert": "circuit_breaker_flapping",
                "severity": "critical",
                "current": int(cb_opens),
                "threshold": thresholds["circuit_breaker_opens_per_hour_max"],
                "recommendation": "Provider instability; consider manual failover to alternate model",
            })

        # Emit alert metrics
        for alert in alerts:
            m.inc("alert_triggered_total", labels={
                "alert": alert["alert"], "severity": alert["severity"]})
            try:
                log.warning("alert_triggered", **{k: v for k, v in alert.items()
                                                   if k != "recommendation"})
            except Exception as _exc:
                log.warning("swallowed_exception", action="alert_log_emit", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

        return alerts

    except Exception as e:
        log.debug("alert_evaluation_failed", err=str(e)[:80])
        return []


# ═══════════════════════════════════════════════════════════════
# INSTALL ALL
# ═══════════════════════════════════════════════════════════════

def install_instrumentation(start_snapshots: bool = True) -> dict[str, bool]:
    """
    Install all instrumentation patches. Call once at startup.

    Returns dict of {component: success} for diagnostics.
    Idempotent: safe to call multiple times.
    """
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return {"already_installed": True}
        results = {
            "meta_orchestrator": _patch_meta_orchestrator(),
            "tool_executor": _patch_tool_executor(),
            "llm_factory": _patch_llm_factory(),
            "memory_facade": _patch_memory_facade(),
            "improvement_loop": _patch_improvement_loop(),
            "trace_bridge": _patch_trace(),
        }
        if start_snapshots:
            start_snapshot_persistence()
            results["snapshot_persistence"] = True
        _INSTALLED = True
        log.info("metrics_bridge.installed", results=results)
        return results


def is_installed() -> bool:
    return _INSTALLED
