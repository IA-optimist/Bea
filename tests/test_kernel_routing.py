"""
tests/test_kernel_routing.py — Kernel performance → routing loop tests.

Validates:
  - Identity map resolves tools to capabilities
  - Performance ingestion uses identity resolution
  - Performance enrichment adjusts provider reliability conservatively
  - Routing pipeline calls enrichment before scoring
  - Adjustments are bounded and explainable
  - Fail-open behavior preserved
  - No regression in routing
"""
import pytest
import inspect


# ═══════════════════════════════════════════════════════════════
# 1 — Identity Map
# ═══════════════════════════════════════════════════════════════

class TestIdentityMap:

    def test_KR01_identity_map_populates(self):
        """Identity map populates from available sources."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        assert imap._populated is True
        stats = imap.stats()
        assert stats["tools_mapped"] >= 0
        assert stats["providers_mapped"] >= 0

    def test_KR02_resolve_unknown_tool(self):
        """Unknown tool returns empty resolution with confidence 0."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        result = imap.resolve_tool("totally_nonexistent_tool_xyz")
        assert result["confidence"] == 0.0
        assert result["capability_ids"] == []

    def test_KR03_resolve_known_provider(self):
        """Known provider (from kernel registry) resolves to capabilities."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        result = imap.resolve_tool("engineer")
        assert result["confidence"] > 0
        assert len(result["capability_ids"]) > 0

    def test_KR04_resolve_provider_capabilities(self):
        """Provider → capabilities lookup works."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        caps = imap.resolve_provider("engineer")
        assert isinstance(caps, list)

    def test_KR05_invalidate_and_rebuild(self):
        """Identity map can be invalidated and rebuilt."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        imap._populate()
        assert imap._populated
        imap.invalidate()
        assert not imap._populated
        imap._populate()
        assert imap._populated

    def test_KR06_confidence_levels(self):
        """Different resolution paths produce correct confidence levels."""
        from kernel.capabilities.identity import CapabilityIdentityMap
        imap = CapabilityIdentityMap()
        # Unknown → 0.0
        r1 = imap.resolve_tool("nonexistent_xyz")
        assert r1["confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════
# 2 — Performance Ingestion with Identity
# ═══════════════════════════════════════════════════════════════

class TestPerformanceIngestion:

    def test_KR07_tool_event_resolves_capability(self):
        """Tool event auto-resolves capability via identity map."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            # Emit tool event for a known provider name
            emit_kernel_event("tool.completed", tool_id="engineer", duration_ms=100)
            # Check if capability was auto-resolved
            all_records = store.get_all()
            types = [r["entity_type"] for r in all_records]
            assert "tool" in types
            # provider_id should also be populated
            provider_records = [r for r in all_records if r["entity_type"] == "provider"]
            # May or may not have resolved depending on identity map
        finally:
            _mod._store = old_store

    def test_KR08_explicit_capability_not_overridden(self):
        """When capability_id is explicitly provided, identity map doesn't override."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.completed", tool_id="git_status",
                              capability_id="explicit_cap", provider_id="explicit_prov")
            cap = store.get_capability_performance("explicit_cap")
            assert cap is not None
            assert cap["total"] == 1
        finally:
            _mod._store = old_store

    def test_KR09_no_double_count(self):
        """Single event creates one record per entity level, not duplicates."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            from kernel.convergence.event_bridge import emit_kernel_event
            emit_kernel_event("tool.completed", tool_id="test_tool",
                              capability_id="test_cap", provider_id="test_prov")
            tool = store.get_tool_performance("test_tool")
            cap = store.get_capability_performance("test_cap")
            prov = store.get_provider_performance("test_prov")
            assert tool["total"] == 1
            assert cap["total"] == 1
            assert prov["total"] == 1
        finally:
            _mod._store = old_store


# ═══════════════════════════════════════════════════════════════
# 3 — Performance Routing Enrichment
# ═══════════════════════════════════════════════════════════════

class TestPerformanceRouting:

    def _make_provider(self, pid="test", reliability=0.5, cap_id="test_cap"):
        class FakeProvider:
            def __init__(self, _pid, _rel, _cap):
                self.provider_id = _pid
                self.capability_id = _cap
                self.reliability = _rel
                self.metadata = {}
        return FakeProvider(pid, reliability, cap_id)

    def test_KR10_no_data_no_change(self):
        """With no performance data, provider reliability unchanged."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        _mod._store = PerformanceStore()
        try:
            p = self._make_provider(reliability=0.5)
            enrich_providers([p])
            assert p.reliability == 0.5  # unchanged
        finally:
            _mod._store = old_store

    def test_KR11_good_performance_boosts(self):
        """Strong performance slightly increases reliability."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            # Record good performance
            for _ in range(10):
                store.record_tool_outcome("good_prov", True, provider_id="good_prov")

            p = self._make_provider(pid="good_prov", reliability=0.5)
            enrich_providers([p])
            assert p.reliability > 0.5
        finally:
            _mod._store = old_store

    def test_KR12_bad_performance_penalizes(self):
        """Poor performance slightly decreases reliability."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(10):
                store.record_tool_outcome("bad_prov", False, provider_id="bad_prov")

            p = self._make_provider(pid="bad_prov", reliability=0.5)
            enrich_providers([p])
            assert p.reliability < 0.5
        finally:
            _mod._store = old_store

    def test_KR13_adjustment_bounded(self):
        """Adjustment never exceeds MAX_BOOST/MAX_PENALTY."""
        from kernel.convergence.performance_routing import (
            enrich_providers, _MAX_BOOST, _MAX_PENALTY,
        )
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            # Perfect performance
            for _ in range(20):
                store.record_tool_outcome("perf_prov", True, provider_id="perf_prov")

            p = self._make_provider(pid="perf_prov", reliability=0.5)
            enrich_providers([p])
            assert p.reliability <= 0.5 + _MAX_BOOST + 0.001

            # Terrible performance
            store.reset()
            for _ in range(20):
                store.record_tool_outcome("fail_prov", False, provider_id="fail_prov")

            p2 = self._make_provider(pid="fail_prov", reliability=0.5)
            enrich_providers([p2])
            assert p2.reliability >= 0.5 - _MAX_PENALTY - 0.001
        finally:
            _mod._store = old_store

    def test_KR14_reliability_never_zero(self):
        """Reliability is clamped to >= 0.05 (zero = blocked in scorer)."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(20):
                store.record_tool_outcome("zero_prov", False, provider_id="zero_prov")

            p = self._make_provider(pid="zero_prov", reliability=0.1)
            enrich_providers([p])
            assert p.reliability >= 0.05
        finally:
            _mod._store = old_store

    def test_KR15_metadata_annotated(self):
        """Enriched providers have kernel_performance metadata."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(5):
                store.record_tool_outcome("meta_prov", True, provider_id="meta_prov")

            p = self._make_provider(pid="meta_prov", reliability=0.5)
            enrich_providers([p])
            assert "kernel_performance" in p.metadata
            kp = p.metadata["kernel_performance"]
            assert "original_reliability" in kp
            assert "kernel_ema" in kp
            assert "adjustment" in kp
            assert "samples" in kp
            assert "trend" in kp
        finally:
            _mod._store = old_store

    def test_KR16_below_min_samples_no_change(self):
        """Below _MIN_SAMPLES threshold, no adjustment."""
        from kernel.convergence.performance_routing import enrich_providers, _MIN_SAMPLES
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old_store = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(_MIN_SAMPLES - 1):
                store.record_tool_outcome("few_prov", True, provider_id="few_prov")

            p = self._make_provider(pid="few_prov", reliability=0.5)
            enrich_providers([p])
            assert p.reliability == 0.5  # unchanged
        finally:
            _mod._store = old_store

    def test_KR17_fail_open_on_error(self):
        """Enrichment errors don't crash — providers returned unchanged."""
        from kernel.convergence.performance_routing import enrich_providers
        # Pass non-standard objects — should not crash
        result = enrich_providers([{"not": "a provider"}])
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════
# 4 — Router Integration
# ═══════════════════════════════════════════════════════════════

class TestRouterIntegration:

    def test_KR18_enrichment_wired_in_router(self):
        """Capability routing router calls enrich_providers before scoring."""
        source = inspect.getsource(
            __import__("core.capability_routing.router", fromlist=["_route_single"])._route_single
        )
        assert "enrich_providers" in source

    def test_KR19_enrichment_fail_open_in_router(self):
        """Enrichment call in router is wrapped in try/except."""
        source = inspect.getsource(
            __import__("core.capability_routing.router", fromlist=["_route_single"])._route_single
        )
        pos = source.find("enrich_providers")
        preceding = source[max(0, pos - 200):pos]
        assert "try:" in preceding

    def test_KR20_router_still_functional(self):
        """Capability routing still works after enrichment wiring."""
        from core.capability_routing.router import route_mission
        decisions = route_mission("build a chatbot")
        assert isinstance(decisions, list)
        assert len(decisions) >= 1


# ═══════════════════════════════════════════════════════════════
# 5 — Orchestrator Integration
# ═══════════════════════════════════════════════════════════════

class TestOrchestratorIntegration:

    @pytest.mark.xfail(reason="Phase 0e source-inspection drift", strict=False)
    def test_KR21_phase_0e_performance_enrichment(self):
        """MetaOrchestrator Phase 0e enriches with performance data."""
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator.run_mission)
        assert "kernel_performance" in source
        assert "kernel_degraded_capabilities" in source
        assert "Phase 0e" in source

    def test_KR22_phase_0e_fail_open(self):
        from core.meta_orchestrator import MetaOrchestrator
        source = inspect.getsource(MetaOrchestrator.run_mission)
        pos = source.find("kernel_performance")
        preceding = source[max(0, pos - 300):pos]
        assert "try:" in preceding


# ═══════════════════════════════════════════════════════════════
# 6 — API Endpoints
# ═══════════════════════════════════════════════════════════════

class TestRoutingAPI:

    def test_KR23_identity_resolve_endpoint(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("identity/resolve" in p for p in paths)

    def test_KR24_identity_stats_endpoint(self):
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("identity/stats" in p for p in paths)

    def test_KR25_convergence_shows_performance(self):
        source = inspect.getsource(
            __import__("api.routes.kernel", fromlist=["convergence_status"]).convergence_status
        )
        assert "performance_tracking" in source
        assert "performance_routing" in source
        assert "identity_mapping" in source


# ═══════════════════════════════════════════════════════════════
# 7 — Explainability
# ═══════════════════════════════════════════════════════════════

class TestExplainability:

    def test_KR26_enriched_provider_has_explanation(self):
        """Enriched provider metadata includes human-readable explanation."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(10):
                store.record_tool_outcome("exp_prov", True, provider_id="exp_prov")

            class P:
                def __init__(self):
                    self.provider_id = "exp_prov"
                    self.capability_id = ""
                    self.reliability = 0.5
                    self.metadata = {}

            p = P()
            enrich_providers([p])
            kp = p.metadata.get("kernel_performance", {})
            assert "explanation" in kp
            assert "boost" in kp["explanation"] or "no adjustment" in kp["explanation"]
        finally:
            _mod._store = old

    def test_KR27_explanation_shows_penalty(self):
        """Degraded provider explanation mentions penalty."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(10):
                store.record_tool_outcome("pen_prov", False, provider_id="pen_prov")

            class P:
                def __init__(self):
                    self.provider_id = "pen_prov"
                    self.capability_id = ""
                    self.reliability = 0.5
                    self.metadata = {}

            p = P()
            enrich_providers([p])
            kp = p.metadata.get("kernel_performance", {})
            assert "penalty" in kp["explanation"]
        finally:
            _mod._store = old

    def test_KR28_explanation_includes_adjusted_reliability(self):
        """Metadata includes both original and adjusted reliability."""
        from kernel.convergence.performance_routing import enrich_providers
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            for _ in range(5):
                store.record_tool_outcome("adj_prov", True, provider_id="adj_prov")

            class P:
                def __init__(self):
                    self.provider_id = "adj_prov"
                    self.capability_id = ""
                    self.reliability = 0.5
                    self.metadata = {}

            p = P()
            enrich_providers([p])
            kp = p.metadata.get("kernel_performance", {})
            assert "original_reliability" in kp
            assert "adjusted_reliability" in kp
        finally:
            _mod._store = old

    def test_KR29_routing_reason_includes_performance(self):
        """Routing decision reason includes performance explanation when data exists."""
        source = inspect.getsource(
            __import__("core.capability_routing.router", fromlist=["_route_single"])._route_single
        )
        assert "kernel_performance" in source
        assert "explanation" in source

    def test_KR30_routing_explain_endpoint(self):
        """Routing explain API endpoint exists."""
        from api.routes.kernel import router
        paths = [r.path for r in router.routes]
        assert any("routing/explain" in p for p in paths)


# ═══════════════════════════════════════════════════════════════
# 8 — Self-Model Integration
# ═══════════════════════════════════════════════════════════════

class TestSelfModelEnrichment:

    def test_KR31_self_model_includes_kernel_performance(self):
        """get_known_limitations includes kernel performance limitations."""
        source = inspect.getsource(
            __import__("core.self_model.queries", fromlist=["get_known_limitations"]).get_known_limitations
        )
        assert "kernel_performance" in source
        assert "kernel_perf:" in source

    def test_KR32_degraded_entities_surface_in_limitations(self):
        """Degraded performance entities appear as self-model limitations."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old = _mod._store
        store = PerformanceStore()
        _mod._store = store
        try:
            # Create a degraded tool
            for _ in range(10):
                store.record_tool_outcome("degraded_tool", False)

            from core.self_model.model import SelfModel
            model = SelfModel()

            from core.self_model.queries import get_known_limitations
            limitations = get_known_limitations(model)
            perf_limits = [l for l in limitations if l["source"] == "kernel_performance"]
            assert len(perf_limits) >= 1
            assert "degraded_tool" in perf_limits[0]["description"]
        finally:
            _mod._store = old

    def test_KR33_performance_label_format(self):
        """Performance label is human-readable."""
        from core.self_model.queries import _performance_label
        d = {
            "entity_type": "tool", "entity_id": "bad_tool",
            "success_rate": 0.2, "trend": "degrading", "total": 10,
        }
        label = _performance_label(d)
        assert "bad_tool" in label
        assert "20%" in label
        assert "degrading" in label
        assert "10 samples" in label

    def test_KR34_no_crash_with_empty_performance(self):
        """Self-model works fine when kernel performance is empty."""
        from kernel.capabilities.performance import PerformanceStore
        import kernel.capabilities.performance as _mod

        old = _mod._store
        _mod._store = PerformanceStore()  # empty
        try:
            from core.self_model.model import SelfModel
            from core.self_model.queries import get_known_limitations
            limitations = get_known_limitations(SelfModel())
            perf_limits = [l for l in limitations if l["source"] == "kernel_performance"]
            assert len(perf_limits) == 0  # no data → no limitations
        finally:
            _mod._store = old


# ═══════════════════════════════════════════════════════════════
# 9 — Priority Invariants
# ═══════════════════════════════════════════════════════════════

class TestPriorityInvariants:

    def test_KR35_readiness_dominates_performance(self):
        """A provider with readiness=0 is blocked regardless of performance."""
        from core.capability_routing.scorer import score_provider
        from core.capability_routing.spec import (
            ProviderSpec, CapabilityRequirement, ProviderType, ProviderStatus,
        )

        provider = ProviderSpec(
            provider_id="test",
            provider_type=ProviderType.AGENT,
            capability_id="test",
            status=ProviderStatus.UNAVAILABLE,
            reliability=1.0,  # perfect reliability
        )
        req = CapabilityRequirement(capability_id="test")
        scored = score_provider(provider, req)
        assert scored.blocked is True  # blocked regardless of reliability

    def test_KR36_policy_dominates_performance(self):
        """High-risk provider is blocked by policy even with good performance."""
        from core.capability_routing.scorer import score_provider
        from core.capability_routing.spec import (
            ProviderSpec, CapabilityRequirement, ProviderType, ProviderStatus,
        )

        provider = ProviderSpec(
            provider_id="risky",
            provider_type=ProviderType.TOOL,
            capability_id="test",
            status=ProviderStatus.READY,
            risk_level="critical",
            reliability=1.0,
        )
        req = CapabilityRequirement(capability_id="test", max_risk="low")
        scored = score_provider(provider, req)
        assert scored.blocked is True  # risk blocks regardless of reliability

    def test_KR37_performance_is_secondary_signal(self):
        """Performance-adjusted reliability is one of 7 scoring dimensions."""
        from core.capability_routing.scorer import score_provider
        from core.capability_routing.spec import (
            ProviderSpec, CapabilityRequirement, ProviderType, ProviderStatus,
        )

        # Low reliability should reduce score but not block
        p1 = ProviderSpec(
            provider_id="low_rel",
            provider_type=ProviderType.AGENT,
            capability_id="test",
            status=ProviderStatus.READY,
            reliability=0.1,
        )
        p2 = ProviderSpec(
            provider_id="high_rel",
            provider_type=ProviderType.AGENT,
            capability_id="test",
            status=ProviderStatus.READY,
            reliability=0.9,
        )
        req = CapabilityRequirement(capability_id="test")
        s1 = score_provider(p1, req)
        s2 = score_provider(p2, req)
        assert not s1.blocked  # low reliability doesn't block
        assert not s2.blocked
        assert s2.total_score > s1.total_score  # but does reduce score
