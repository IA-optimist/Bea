"""
tests/test_kernel_performance.py — Kernel performance intelligence tests.

Validates:
  - PerformanceRecord math (success rate, EMA, duration, trend, confidence)
  - PerformanceStore recording and querying
  - Event bridge integration (tool.completed/failed update performance)
  - Runtime integration (kernel boot, MetaOrchestrator enrichment)
  - API endpoints
  - Fail-open behavior
"""
import pytest


# ═══════════════════════════════════════════════════════════════
# 1 — PerformanceRecord
# ═══════════════════════════════════════════════════════════════

class TestPerformanceRecord:

    def test_KP01_initial_state(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        assert r.total == 0
        assert r.success_rate == 0.0
        assert r.confidence == 0.0
        assert r.trend == "unknown"

    def test_KP02_single_success(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        r.record_outcome(True, duration_ms=150)
        assert r.total == 1
        assert r.successes == 1
        assert r.success_rate == 1.0
        assert r.avg_duration_ms == 150

    def test_KP03_single_failure(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        r.record_outcome(False, duration_ms=5000)
        assert r.total == 1
        assert r.failures == 1
        assert r.success_rate == 0.0
        assert r.failure_rate == 1.0

    def test_KP04_mixed_outcomes(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        for _ in range(7):
            r.record_outcome(True, duration_ms=100)
        for _ in range(3):
            r.record_outcome(False, duration_ms=200)
        assert r.total == 10
        assert r.success_rate == 0.7
        assert r.failure_rate == 0.3
        assert r.avg_duration_ms == 130  # (7*100 + 3*200) / 10

    def test_KP05_ema_weights_recent(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        # Start with failures
        for _ in range(10):
            r.record_outcome(False)
        ema_after_failures = r.ema_success
        # Now successes
        for _ in range(5):
            r.record_outcome(True)
        # EMA should be higher than after failures but still reflect history
        assert r.ema_success > ema_after_failures
        assert r.ema_success < 1.0  # not purely recent

    def test_KP06_duration_tracking(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        r.record_outcome(True, duration_ms=100)
        r.record_outcome(True, duration_ms=300)
        r.record_outcome(True, duration_ms=200)
        assert r.min_duration_ms == 100
        assert r.max_duration_ms == 300
        assert r.avg_duration_ms == 200

    def test_KP07_trend_stable(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        for _ in range(10):
            r.record_outcome(True)
        assert r.trend == "stable"

    def test_KP08_trend_degrading(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        # First half: mostly success
        for _ in range(5):
            r.record_outcome(True)
        # Second half: mostly failure
        for _ in range(5):
            r.record_outcome(False)
        assert r.trend == "degrading"

    def test_KP09_trend_improving(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        for _ in range(5):
            r.record_outcome(False)
        for _ in range(5):
            r.record_outcome(True)
        assert r.trend == "improving"

    def test_KP10_confidence_increases_with_samples(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        r.record_outcome(True)
        c1 = r.confidence
        for _ in range(10):
            r.record_outcome(True)
        c2 = r.confidence
        assert c2 > c1

    def test_KP11_recent_window_bounded(self):
        from kernel.capabilities.performance import PerformanceRecord, _RECENT_WINDOW
        r = PerformanceRecord(entity_id="test", entity_type="tool")
        for _ in range(100):
            r.record_outcome(True)
        assert len(r._recent) <= _RECENT_WINDOW

    def test_KP12_serialization(self):
        from kernel.capabilities.performance import PerformanceRecord
        r = PerformanceRecord(entity_id="tool:git_status", entity_type="tool")
        r.record_outcome(True, 150)
        d = r.to_dict()
        assert d["entity_id"] == "tool:git_status"
        assert d["success_rate"] == 1.0
        assert d["avg_duration_ms"] == 150
        assert "confidence" in d
        assert "trend" in d


# ═══════════════════════════════════════════════════════════════
# 2 — PerformanceStore
# ═══════════════════════════════════════════════════════════════

class TestPerformanceStore:

    def test_KP13_record_tool_outcome(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("git_status", True, 50)
        perf = store.get_tool_performance("git_status")
        assert perf is not None
        assert perf["total"] == 1
        assert perf["success_rate"] == 1.0

    def test_KP14_record_updates_capability(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("git_status", True, capability_id="code_generation")
        perf = store.get_capability_performance("code_generation")
        assert perf is not None
        assert perf["total"] == 1

    def test_KP15_record_updates_provider(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("git_status", True, provider_id="engineer")
        perf = store.get_provider_performance("engineer")
        assert perf is not None

    def test_KP16_multiple_tools_tracked(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("git_status", True)
        store.record_tool_outcome("docker_ps", False)
        store.record_tool_outcome("git_status", True)
        git = store.get_tool_performance("git_status")
        docker = store.get_tool_performance("docker_ps")
        assert git["total"] == 2
        assert docker["total"] == 1
        assert git["success_rate"] == 1.0
        assert docker["success_rate"] == 0.0

    def test_KP17_get_all(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("a", True)
        store.record_tool_outcome("b", False)
        all_records = store.get_all()
        assert len(all_records) == 2

    def test_KP18_get_all_filtered(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("a", True, capability_id="cap1")
        tools = store.get_all(entity_type="tool")
        caps = store.get_all(entity_type="capability")
        assert len(tools) == 1
        assert len(caps) == 1

    def test_KP19_get_degraded(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        # Tool with low success rate (need >= 5 samples)
        for _ in range(6):
            store.record_tool_outcome("bad_tool", False)
        for _ in range(6):
            store.record_tool_outcome("good_tool", True)
        degraded = store.get_degraded(threshold=0.5)
        assert len(degraded) == 1
        assert degraded[0]["entity_id"] == "bad_tool"

    def test_KP20_get_summary(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("a", True)
        store.record_tool_outcome("b", False, capability_id="cap1")
        summary = store.get_summary()
        assert summary["total_entities"] >= 2
        assert "tool" in summary["by_type"]

    def test_KP21_reset(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_tool_outcome("a", True)
        assert len(store.get_all()) > 0
        store.reset()
        assert len(store.get_all()) == 0

    def test_KP22_empty_query_returns_none(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        assert store.get_tool_performance("nonexistent") is None

    def test_KP23_step_outcome(self):
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        store.record_step_outcome("s1", True, step_type="skill", capability_id="skill_execution")
        cap = store.get_capability_performance("skill_execution")
        assert cap is not None
        assert cap["total"] == 1

    def test_KP24_survives_multiple_missions(self):
        """Performance accumulates across missions."""
        from kernel.capabilities.performance import PerformanceStore
        store = PerformanceStore()
        for i in range(5):
            store.record_tool_outcome("git_status", i % 2 == 0)
        perf = store.get_tool_performance("git_status")
        assert perf["total"] == 5
        assert perf["successes"] == 3


# ═══════════════════════════════════════════════════════════════
# 3 — Event Bridge Integration
# ═══════════════════════════════════════════════════════════════

class TestEventBridgePerformance:

    def test_KP25_tool_completed_updates_performance(self):
        """emit_kernel_event('tool.completed') updates performance store."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.completed", tool_id="test_tool", duration_ms=200)
            perf = store.get_tool_performance("test_tool")
            assert perf is not None
            assert perf["total"] == 1
            assert perf["success_rate"] == 1.0
            assert perf["avg_duration_ms"] == 200
        finally:
            _mod._store = old_store

    def test_KP26_tool_failed_updates_performance(self):
        """emit_kernel_event('tool.failed') updates performance store."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.failed", tool_id="bad_tool", duration_ms=5000)
            perf = store.get_tool_performance("bad_tool")
            assert perf is not None
            assert perf["total"] == 1
            assert perf["success_rate"] == 0.0
        finally:
            _mod._store = old_store

    def test_KP27_step_completed_updates_performance(self):
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("step.completed", step_id="s1",
                              capability_id="skill_execution", provider_id="analyst")
            cap = store.get_capability_performance("skill_execution")
            prov = store.get_provider_performance("analyst")
            assert cap is not None
            assert prov is not None
        finally:
            _mod._store = old_store

    def test_KP28_non_outcome_events_dont_update(self):
        """Events like tool.invoked, step.started don't update performance."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.invoked", tool_id="test_tool")
            emit_kernel_event("step.started", step_id="s1")
            emit_kernel_event("mission.created", mission_id="m1")
            assert len(store.get_all()) == 0
        finally:
            _mod._store = old_store

    def test_KP29_performance_update_fail_open(self):
        """Performance update failures don't crash event bridge."""
        from kernel.convergence.event_bridge import emit_kernel_event
        # Even with corrupted duration, should not crash
        result = emit_kernel_event("tool.completed", tool_id="test", duration_ms="not_a_number")
        assert result is True  # bridge succeeds even if perf update has weird data


# ═══════════════════════════════════════════════════════════════
# 4 — Kernel Boot Integration
# ═══════════════════════════════════════════════════════════════

class TestKernelBootPerformance:

    def test_KP30_performance_in_runtime(self):
        """Kernel runtime includes performance store."""
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        assert runtime.performance is not None
        status = runtime.status()
        assert status["subsystems"]["performance"] is True

    def test_KP31_runtime_performance_queryable(self):
        """Runtime performance store is functional."""
        from kernel.runtime.boot import boot_kernel
        runtime = boot_kernel()
        summary = runtime.performance.get_summary()
        assert isinstance(summary, dict)
        assert "total_entities" in summary


# ═══════════════════════════════════════════════════════════════
# 5 — MetaOrchestrator Integration
# ═══════════════════════════════════════════════════════════════

class TestOrchestratorPerformance:

    @pytest.mark.stale
    @pytest.mark.xfail(reason="Phase 0e in run_mission drift", strict=False)
    def test_KP32_phase_0e_in_orchestrator(self):
        """MetaOrchestrator has kernel performance enrichment phase."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator.run_mission)
        assert "kernel_performance" in source
        assert "kernel_degraded_capabilities" in source
        assert "Phase 0e" in source

    def test_KP33_phase_0e_fail_open(self):
        """Performance enrichment is wrapped in try/except."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator.run_mission)
        pos = source.find("kernel_performance")
        preceding = source[max(0, pos - 300):pos]
        assert "try:" in preceding


# ═══════════════════════════════════════════════════════════════
# 6 — API Endpoints
# ═══════════════════════════════════════════════════════════════

class TestPerformanceAPI:

    def test_KP34_api_endpoints_exist(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("performance" in p for p in paths)

    def test_KP35_api_has_summary(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("performance/summary" in p for p in paths)

    def test_KP36_api_has_degraded(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("performance/degraded" in p for p in paths)

    def test_KP37_api_has_entity_lookup(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("{entity_type}" in p and "{entity_id}" in p for p in paths)
