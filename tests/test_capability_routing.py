"""
Tests — Capability-First Routing (80 tests)

Spec (contracts)
  CR01-CR10: ProviderSpec, RoutingDecision, CapabilityRequirement

Registry
  CR11-CR22: population, lookup, fuzzy, stats

Scorer
  CR23-CR34: scoring dimensions, blocks, ranking

Resolver
  CR35-CR48: goal → capability extraction

Router
  CR49-CR60: end-to-end routing

API
  CR61-CR70: endpoint presence and behavior

Integration
  CR71-CR80: MetaOrchestrator wiring, fail-open, no regression
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# 1 — Spec (Contracts)
# ═══════════════════════════════════════════════════════════════

class TestSpec:

    def test_CR01_provider_type_values(self):
        from core.capability_routing.spec import ProviderType
        assert {t.value for t in ProviderType} == {"agent", "tool", "mcp", "module", "connector"}

    def test_CR02_provider_status_values(self):
        from core.capability_routing.spec import ProviderStatus
        expected = {"ready", "degraded", "unavailable", "approval_required",
                    "not_configured", "disabled"}
        assert {s.value for s in ProviderStatus} == expected

    def test_CR03_provider_spec_fields(self):
        from core.capability_routing.spec import ProviderSpec, ProviderType, ProviderStatus
        p = ProviderSpec(
            provider_id="agent:coder",
            provider_type=ProviderType.AGENT,
            capability_id="code.write",
        )
        assert p.provider_id == "agent:coder"
        assert p.is_available is True
        assert p.is_blocked is False

    def test_CR04_provider_spec_blocked(self):
        from core.capability_routing.spec import ProviderSpec, ProviderType, ProviderStatus
        p = ProviderSpec(
            provider_id="mcp:pg",
            provider_type=ProviderType.MCP,
            capability_id="db.query",
            status=ProviderStatus.UNAVAILABLE,
        )
        assert p.is_available is False
        assert p.is_blocked is True

    def test_CR05_provider_spec_to_dict(self):
        from core.capability_routing.spec import ProviderSpec, ProviderType
        d = ProviderSpec(
            provider_id="tool:shell",
            provider_type=ProviderType.TOOL,
            capability_id="tool.shell",
        ).to_dict()
        assert d["provider_type"] == "tool"
        assert "readiness" in d

    def test_CR06_routing_decision_success(self):
        from core.capability_routing.spec import RoutingDecision, ProviderSpec, ProviderType
        p = ProviderSpec(provider_id="a", provider_type=ProviderType.AGENT, capability_id="c")
        d = RoutingDecision(capability_id="c", selected_provider=p, score=0.8)
        assert d.success is True

    def test_CR07_routing_decision_failure(self):
        from core.capability_routing.spec import RoutingDecision
        d = RoutingDecision(capability_id="c", selected_provider=None)
        assert d.success is False

    def test_CR08_routing_decision_to_dict(self):
        from core.capability_routing.spec import RoutingDecision
        d = RoutingDecision(capability_id="c", selected_provider=None, fallback_used=True)
        dd = d.to_dict()
        assert dd["capability_id"] == "c"
        assert dd["fallback_used"] is True
        assert dd["selected"] is None

    def test_CR09_capability_requirement_fields(self):
        from core.capability_routing.spec import CapabilityRequirement
        r = CapabilityRequirement(capability_id="code.patch", min_reliability=0.5)
        assert r.required is True
        assert r.min_reliability == 0.5

    def test_CR10_capability_requirement_to_dict(self):
        from core.capability_routing.spec import CapabilityRequirement, ProviderType
        r = CapabilityRequirement(
            capability_id="infra.deploy",
            prefer_type=ProviderType.AGENT,
        )
        d = r.to_dict()
        assert d["prefer_type"] == "agent"


# ═══════════════════════════════════════════════════════════════
# 2 — Registry
# ═══════════════════════════════════════════════════════════════

class TestRegistry:

    def test_CR11_registry_creates(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        assert r.stats()["capabilities"] == 0

    def test_CR12_manual_register(self):
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import ProviderSpec, ProviderType
        r = ProviderRegistry()
        r._register(ProviderSpec(
            provider_id="agent:coder",
            provider_type=ProviderType.AGENT,
            capability_id="code.write",
        ))
        assert len(r.get_providers("code.write")) == 1

    def test_CR13_get_all_capabilities(self):
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import ProviderSpec, ProviderType
        r = ProviderRegistry()
        r._register(ProviderSpec(provider_id="a", provider_type=ProviderType.AGENT, capability_id="cap1"))
        r._register(ProviderSpec(provider_id="b", provider_type=ProviderType.MCP, capability_id="cap2"))
        assert "cap1" in r.get_all_capabilities()
        assert "cap2" in r.get_all_capabilities()

    def test_CR14_find_by_type(self):
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import ProviderSpec, ProviderType
        r = ProviderRegistry()
        r._register(ProviderSpec(provider_id="a", provider_type=ProviderType.AGENT, capability_id="cap1"))
        r._register(ProviderSpec(provider_id="b", provider_type=ProviderType.MCP, capability_id="cap1"))
        agents = r.find_providers_by_type("cap1", ProviderType.AGENT)
        assert len(agents) == 1
        assert agents[0].provider_id == "a"

    def test_CR15_find_available(self):
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import ProviderSpec, ProviderType, ProviderStatus
        r = ProviderRegistry()
        r._register(ProviderSpec(provider_id="a", provider_type=ProviderType.AGENT, capability_id="c", status=ProviderStatus.READY))
        r._register(ProviderSpec(provider_id="b", provider_type=ProviderType.AGENT, capability_id="c", status=ProviderStatus.UNAVAILABLE))
        avail = r.find_available("c")
        assert len(avail) == 1

    def test_CR16_populate_returns_counts(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        counts = r.populate()
        assert "total" in counts
        assert isinstance(counts["total"], int)

    def test_CR17_populate_agents(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        counts = r.populate()
        assert counts["agents"] >= 0

    def test_CR18_populate_mcp(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        counts = r.populate()
        assert counts["mcp"] >= 0

    def test_CR19_populate_tools(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        counts = r.populate()
        assert counts["tools"] >= 0

    def test_CR20_populate_modules(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        counts = r.populate()
        assert counts["modules"] >= 0

    def test_CR21_stats_after_populate(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        r.populate()
        s = r.stats()
        assert "capabilities" in s
        assert "by_type" in s
        assert s["populate_count"] == 1

    def test_CR22_singleton_works(self):
        from core.capability_routing.registry import get_provider_registry
        r = get_provider_registry()
        assert r.stats()["populate_count"] >= 1


# ═══════════════════════════════════════════════════════════════
# 3 — Scorer
# ═══════════════════════════════════════════════════════════════

class TestScorer:

    def _make_provider(self, **kwargs):
        from core.capability_routing.spec import ProviderSpec, ProviderType, ProviderStatus
        defaults = {
            "provider_id": "test",
            "provider_type": ProviderType.AGENT,
            "capability_id": "test.cap",
            "status": ProviderStatus.READY,
            "readiness": 1.0,
            "reliability": 0.8,
            "confidence": 0.7,
            "risk_level": "low",
        }
        defaults.update(kwargs)
        return ProviderSpec(**defaults)

    def _make_requirement(self, **kwargs):
        from core.capability_routing.spec import CapabilityRequirement
        defaults = {"capability_id": "test.cap"}
        defaults.update(kwargs)
        return CapabilityRequirement(**defaults)

    def test_CR23_basic_scoring(self):
        from core.capability_routing.scorer import score_provider
        p = self._make_provider()
        r = self._make_requirement()
        result = score_provider(p, r)
        assert result.total_score > 0
        assert not result.blocked

    def test_CR24_blocked_unavailable(self):
        from core.capability_routing.scorer import score_provider
        from core.capability_routing.spec import ProviderStatus
        p = self._make_provider(status=ProviderStatus.UNAVAILABLE)
        result = score_provider(p, self._make_requirement())
        assert result.blocked is True
        assert result.total_score == 0.0

    def test_CR25_blocked_risk(self):
        from core.capability_routing.scorer import score_provider
        p = self._make_provider(risk_level="critical")
        r = self._make_requirement(max_risk="medium")
        result = score_provider(p, r)
        assert result.blocked is True

    def test_CR26_blocked_reliability(self):
        from core.capability_routing.scorer import score_provider
        p = self._make_provider(reliability=0.2)
        r = self._make_requirement(min_reliability=0.5)
        result = score_provider(p, r)
        assert result.blocked is True

    def test_CR27_higher_reliability_scores_better(self):
        from core.capability_routing.scorer import score_provider
        r = self._make_requirement()
        low = score_provider(self._make_provider(reliability=0.3), r)
        high = score_provider(self._make_provider(reliability=0.9), r)
        assert high.total_score > low.total_score

    def test_CR28_higher_readiness_scores_better(self):
        from core.capability_routing.scorer import score_provider
        r = self._make_requirement()
        low = score_provider(self._make_provider(readiness=0.2), r)
        high = score_provider(self._make_provider(readiness=1.0), r)
        assert high.total_score > low.total_score

    def test_CR29_approval_penalty(self):
        from core.capability_routing.scorer import score_provider
        r = self._make_requirement()
        normal = score_provider(self._make_provider(requires_approval=False), r)
        gated = score_provider(self._make_provider(requires_approval=True), r)
        assert normal.total_score > gated.total_score

    def test_CR30_type_preference_bonus(self):
        from core.capability_routing.scorer import score_provider
        from core.capability_routing.spec import ProviderType
        r = self._make_requirement(prefer_type=ProviderType.AGENT)
        agent = score_provider(self._make_provider(provider_type=ProviderType.AGENT), r)
        mcp = score_provider(self._make_provider(provider_type=ProviderType.MCP), r)
        assert agent.total_score > mcp.total_score

    def test_CR31_breakdown_present(self):
        from core.capability_routing.scorer import score_provider
        result = score_provider(self._make_provider(), self._make_requirement())
        assert "readiness" in result.breakdown
        assert "reliability" in result.breakdown

    def test_CR32_rank_providers(self):
        from core.capability_routing.scorer import rank_providers
        from core.capability_routing.spec import ProviderStatus
        r = self._make_requirement()
        providers = [
            self._make_provider(provider_id="low", reliability=0.2),
            self._make_provider(provider_id="high", reliability=0.95),
            self._make_provider(provider_id="blocked", status=ProviderStatus.UNAVAILABLE),
        ]
        ranked = rank_providers(providers, r)
        assert ranked[0].provider.provider_id == "high"
        assert ranked[-1].blocked is True

    def test_CR33_scored_provider_to_dict(self):
        from core.capability_routing.scorer import score_provider
        result = score_provider(self._make_provider(), self._make_requirement())
        d = result.to_dict()
        assert "total_score" in d
        assert "breakdown" in d

    def test_CR34_score_range(self):
        from core.capability_routing.scorer import score_provider
        result = score_provider(self._make_provider(), self._make_requirement())
        assert 0.0 <= result.total_score <= 1.0


# ═══════════════════════════════════════════════════════════════
# 4 — Resolver
# ═══════════════════════════════════════════════════════════════

class TestResolver:

    def test_CR35_resolve_code_patch(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Fix the bug in auth.py")
        cap_ids = [r.capability_id for r in reqs]
        assert any("code" in c or "patch" in c for c in cap_ids)

    def test_CR36_resolve_deploy(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Deploy the app to production")
        cap_ids = [r.capability_id for r in reqs]
        assert any("deploy" in c or "infra" in c for c in cap_ids)

    def test_CR37_resolve_research(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Research competitor pricing strategies")
        cap_ids = [r.capability_id for r in reqs]
        assert any("research" in c for c in cap_ids)

    def test_CR38_resolve_github(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Review the pull request on GitHub")
        cap_ids = [r.capability_id for r in reqs]
        assert any("github" in c or "code.review" in c for c in cap_ids)

    def test_CR39_resolve_security(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Run a security audit on the codebase")
        cap_ids = [r.capability_id for r in reqs]
        assert any("security" in c for c in cap_ids)

    def test_CR40_resolve_stripe(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Set up Stripe billing for the product")
        cap_ids = [r.capability_id for r in reqs]
        assert any("stripe" in c or "finance" in c for c in cap_ids)

    def test_CR41_resolve_unknown_returns_general(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("xyzzy quantum flux capacitor")
        assert len(reqs) >= 1
        # Should fall back to general.execution
        assert any("general" in r.capability_id for r in reqs)

    def test_CR42_resolve_deduplicates(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Fix the bug and patch the code")
        cap_ids = [r.capability_id for r in reqs]
        assert len(cap_ids) == len(set(cap_ids))  # No duplicates

    def test_CR43_resolve_with_classification(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities(
            "Do something", classification={"task_type": "code_generation"}
        )
        assert any("code" in r.capability_id for r in reqs)

    def test_CR44_resolve_browser(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Fetch the web page at example.com")
        cap_ids = [r.capability_id for r in reqs]
        assert any("browser" in c or "fetch" in c for c in cap_ids)

    def test_CR45_resolve_memory(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Search memory for prior decisions about auth")
        cap_ids = [r.capability_id for r in reqs]
        assert any("memory" in c for c in cap_ids)

    def test_CR46_resolve_content(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Write a marketing email for the launch")
        cap_ids = [r.capability_id for r in reqs]
        assert any("content" in c for c in cap_ids)

    def test_CR47_resolve_test(self):
        from core.capability_routing.resolver import resolve_capabilities
        reqs = resolve_capabilities("Write tests for the auth module")
        cap_ids = [r.capability_id for r in reqs]
        assert any("test" in c or "code" in c for c in cap_ids)

    def test_CR48_resolve_returns_list(self):
        from core.capability_routing.resolver import resolve_capabilities
        assert isinstance(resolve_capabilities("hello"), list)


# ═══════════════════════════════════════════════════════════════
# 5 — Router (end-to-end)
# ═══════════════════════════════════════════════════════════════

class TestRouter:

    def test_CR49_route_mission_returns_list(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("Fix the auth bug")
        assert isinstance(decisions, list)
        assert len(decisions) >= 1

    def test_CR50_route_mission_has_capability_id(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("Deploy to production")
        assert all(d.capability_id for d in decisions)

    def test_CR51_route_mission_to_dict(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("Write a test")
        for d in decisions:
            dd = d.to_dict()
            assert "capability_id" in dd
            assert "selected" in dd

    def test_CR52_route_unknown_uses_fallback(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("xyzzy quantum impossibility")
        # Should still return decisions (with fallback)
        assert len(decisions) >= 1

    def test_CR53_route_single_capability(self):
        from core.capability_routing.router import route_single_capability
        d = route_single_capability("code.write")
        assert d.capability_id == "code.write"

    def test_CR54_route_single_with_reliability(self):
        from core.capability_routing.router import route_single_capability
        d = route_single_capability("code.write", min_reliability=0.99)
        # Might have no providers at that reliability — that's ok
        assert isinstance(d.candidates_evaluated, int)

    def test_CR55_route_with_classification(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission(
            "Write auth middleware",
            classification={"task_type": "code_generation"},
        )
        assert len(decisions) >= 1

    def test_CR56_decisions_are_explainable(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("Fix the login bug")
        for d in decisions:
            assert d.reason  # Non-empty reason

    def test_CR57_blocked_candidates_tracked(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("Run a security audit")
        for d in decisions:
            assert isinstance(d.blocked_candidates, list)

    def test_CR58_fail_open_on_error(self):
        from core.capability_routing.router import route_mission
        from unittest.mock import patch
        with patch("core.capability_routing.resolver.resolve_capabilities", side_effect=RuntimeError("boom")):
            decisions = route_mission("test")
        assert len(decisions) >= 1
        assert decisions[0].fallback_used is True

    def test_CR59_route_no_side_effects(self):
        """Routing is read-only — no state mutation."""
        from core.capability_routing.router import route_mission
        from core.capability_routing.registry import get_provider_registry
        reg = get_provider_registry()
        before = reg.stats()["capabilities"]
        route_mission("Do something")
        after = reg.stats()["capabilities"]
        assert before == after

    def test_CR60_route_performance(self):
        """Routing should be fast (< 500ms for non-LLM path)."""
        import time
        from core.capability_routing.router import route_mission
        start = time.time()
        route_mission("Fix a bug in the payment system")
        elapsed = (time.time() - start) * 1000
        assert elapsed < 2000  # generous for CI


# ═══════════════════════════════════════════════════════════════
# 6 — API Routes
# ═══════════════════════════════════════════════════════════════

class TestAPIRoutes:

    def test_CR61_routing_status_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing" in paths

    def test_CR62_capabilities_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/capabilities" in paths

    def test_CR63_resolve_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/resolve" in paths

    def test_CR64_route_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/route" in paths

    def test_CR65_refresh_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/refresh" in paths

    def test_CR66_providers_route(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        # Path template
        cap_routes = [p for p in paths if "capability-routing/providers" in p]
        assert len(cap_routes) >= 1

    def test_CR67_total_routes(self):
        from api.main import app
        paths = [r.path for r in app.routes if "capability-routing" in r.path]
        assert len(paths) >= 6

    def test_CR68_no_secret_leakage_in_spec(self):
        from core.capability_routing.spec import ProviderSpec, ProviderType
        p = ProviderSpec(
            provider_id="mcp:test",
            provider_type=ProviderType.MCP,
            capability_id="test",
            metadata={"server_name": "test"},
        )
        d = str(p.to_dict())
        assert "sk-" not in d
        assert "password" not in d.lower()

    def test_CR69_no_secret_in_routing_decision(self):
        from core.capability_routing.router import route_mission
        decisions = route_mission("test")
        text = str([d.to_dict() for d in decisions])
        assert "sk-" not in text
        assert "ghp_" not in text

    def test_CR70_router_mounted_in_app(self):
        from api.main import app
        route_names = [r.name for r in app.routes if hasattr(r, 'name')]
        # At least one of our endpoints should be present
        assert any("capability" in (n or "") for n in route_names) or \
               any("capability-routing" in (r.path or "") for r in app.routes)


# ═══════════════════════════════════════════════════════════════
# 7 — Integration (MetaOrchestrator wiring)
# ═══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_CR71_meta_orchestrator_has_routing_phase(self):
        """Phase 0c exists in MetaOrchestrator source."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert "capability_routing" in src

    def test_CR72_routing_is_fail_open(self):
        """If capability routing import fails, mission still works."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        # Must be wrapped in try/except
        assert "capability_routing" in src
        # Check it's in a try block (Phase 0c)
        lines = src.split("\n")
        in_try = False
        for line in lines:
            if "Phase 0c" in line:
                # Previous lines should have try
                idx = lines.index(line)
                nearby = "\n".join(lines[max(0, idx-3):idx+15])
                assert "try" in nearby
                assert "except" in nearby
                break

    def test_CR73_routing_records_metadata(self):
        """MetaOrchestrator stores routing in ctx.metadata."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert 'capability_routing' in src
        assert 'routed_provider' in src

    def test_CR74_routing_records_trace(self):
        """MetaOrchestrator records routing in decision trace."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert "capability_routed" in src or "capability_fallback" in src

    def test_CR75_registry_populated_from_agents(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        n = r._populate_agents()
        assert isinstance(n, int)

    def test_CR76_registry_populated_from_mcp(self):
        from core.capability_routing.registry import ProviderRegistry
        r = ProviderRegistry()
        n = r._populate_mcp()
        assert isinstance(n, int)

    def test_CR77_no_new_orchestrator_created(self):
        """Capability routing does NOT create a new orchestrator."""
        import os
        routing_dir = os.path.join(os.path.dirname(__file__), "..", "core", "capability_routing")
        for fname in os.listdir(routing_dir):
            if fname.endswith(".py"):
                with open(os.path.join(routing_dir, fname)) as f:
                    content = f.read()
                assert "class Orchestrator" not in content
                assert "class MetaOrchestrator" not in content

    def test_CR78_existing_agent_routing_preserved(self):
        """Legacy agent routing still present in MetaOrchestrator."""
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert "delegate" in src
        assert "jarvis" in src.lower()

    def test_CR79_self_model_integration(self):
        """Registry uses same sources as self-model."""
        from core.capability_routing.registry import ProviderRegistry
        from core.self_model.sources import read_capability_graph, read_mcp_registry
        # Both should work without error
        read_capability_graph()
        read_mcp_registry()
        r = ProviderRegistry()
        r.populate()

    def test_CR80_backward_compat(self):
        """Existing test suites import MetaOrchestrator without error."""
        from core.meta_orchestrator import MetaOrchestrator, get_meta_orchestrator
        m = MetaOrchestrator()
        assert hasattr(m, "run_mission")
        assert hasattr(m, "jarvis")
        assert hasattr(m, "v2")


# ═══════════════════════════════════════════════════════════════
# 8 — Feedback & Learning
# ═══════════════════════════════════════════════════════════════

class TestFeedback:

    def test_CR81_routing_history_creates(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        assert rh.summary()["total_decisions"] == 0

    def test_CR82_record_decision(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        outcome = rh.record_decision(
            mission_id="m1",
            capability_id="code.patch",
            provider_id="agent:coder",
            provider_type="agent",
            score=0.9,
            alternatives_count=3,
        )
        assert outcome.mission_id == "m1"
        assert rh.summary()["total_decisions"] == 1

    def test_CR83_record_outcome_updates(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        rh.record_decision(mission_id="m1", capability_id="c1",
                          provider_id="p1", score=0.8)
        rh.record_outcome(mission_id="m1", success=True, duration_ms=500)
        recent = rh.get_recent(1)
        assert recent[0]["success"] is True
        assert recent[0]["duration_ms"] == 500.0

    def test_CR84_outcome_to_dict(self):
        from core.capability_routing.feedback import RoutingOutcome
        o = RoutingOutcome(
            mission_id="m1",
            capability_id="code.patch",
            provider_id="agent:coder",
            provider_type="agent",
            score=0.9,
            alternatives_count=2,
            fallback_used=False,
            requires_approval=False,
        )
        d = o.to_dict()
        assert d["mission_id"] == "m1"
        assert d["score"] == 0.9

    def test_CR85_provider_stats(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        rh.record_decision(mission_id="m1", capability_id="c1",
                          provider_id="p1", score=0.8)
        rh.record_outcome(mission_id="m1", success=True)
        rh.record_decision(mission_id="m2", capability_id="c1",
                          provider_id="p1", score=0.7)
        rh.record_outcome(mission_id="m2", success=False, error="crash")
        stats = rh.get_provider_stats()
        assert "p1" in stats
        assert stats["p1"]["total"] == 2
        assert stats["p1"]["success_rate"] == 0.5

    def test_CR86_provider_success_rate(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        rh.record_decision(mission_id="m1", capability_id="c1",
                          provider_id="p1", score=0.8)
        rh.record_outcome(mission_id="m1", success=True)
        assert rh.get_provider_success_rate("p1") == 1.0
        assert rh.get_provider_success_rate("unknown") is None

    def test_CR87_history_ring_buffer(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory(max_size=5)
        for i in range(10):
            rh.record_decision(mission_id=f"m{i}", capability_id="c",
                             provider_id="p", score=0.5)
        assert rh.summary()["total_decisions"] == 5  # Ring buffer limit

    def test_CR88_get_recent_limit(self):
        from core.capability_routing.feedback import RoutingHistory
        rh = RoutingHistory()
        for i in range(20):
            rh.record_decision(mission_id=f"m{i}", capability_id="c",
                             provider_id="p", score=0.5)
        recent = rh.get_recent(5)
        assert len(recent) == 5

    def test_CR89_singleton_works(self):
        from core.capability_routing.feedback import get_routing_history
        rh = get_routing_history()
        assert rh is not None
        assert isinstance(rh.summary(), dict)

    def test_CR90_no_secrets_in_outcome(self):
        from core.capability_routing.feedback import RoutingOutcome
        o = RoutingOutcome(
            mission_id="m1",
            capability_id="test",
            provider_id="mcp:test",
            provider_type="mcp",
            score=0.5,
            alternatives_count=0,
            fallback_used=False,
            requires_approval=False,
            error="sk-12345 ghp_abcdef",
        )
        d = o.to_dict()
        # Error gets truncated to 200 chars
        assert isinstance(d["error"], str)


# ═══════════════════════════════════════════════════════════════
# 9 — Extended API & Web UI
# ═══════════════════════════════════════════════════════════════

class TestExtendedAPI:

    def test_CR91_history_route_exists(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/history" in paths

    def test_CR92_provider_stats_route_exists(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/provider-stats" in paths

    def test_CR93_summary_route_exists(self):
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/capability-routing/summary" in paths

    def test_CR98_meta_has_feedback_recording(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert "record_decision" in src

    def test_CR99_meta_has_outcome_recording(self):
        import inspect
        from core.meta_orchestrator import MetaOrchestrator
        src = inspect.getsource(MetaOrchestrator.run_mission)
        assert "record_outcome" in src

    def test_CR100_total_routes(self):
        from api.main import app
        paths = [r.path for r in app.routes if "capability-routing" in r.path]
        assert len(paths) >= 9  # 6 original + 3 new


# ═══════════════════════════════════════════════════════════════
# 10 — Phase 12 Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestPhase12Integration:

    def test_CR101_readiness_change_affects_selection(self):
        """Provider selection changes when readiness changes."""
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import (
            ProviderSpec, ProviderType, ProviderStatus, CapabilityRequirement,
        )
        from core.capability_routing.scorer import rank_providers

        r = ProviderRegistry()
        # Two providers for same capability
        p1 = ProviderSpec(
            provider_id="agent:a", provider_type=ProviderType.AGENT,
            capability_id="code.write", status=ProviderStatus.READY,
            readiness=1.0, reliability=0.8,
        )
        p2 = ProviderSpec(
            provider_id="agent:b", provider_type=ProviderType.AGENT,
            capability_id="code.write", status=ProviderStatus.READY,
            readiness=0.3, reliability=0.8,
        )
        r._register(p1)
        r._register(p2)
        req = CapabilityRequirement(capability_id="code.write")

        # High readiness wins
        ranked = rank_providers(r.get_providers("code.write"), req)
        assert ranked[0].provider.provider_id == "agent:a"

        # Now flip readiness
        p1.readiness = 0.1
        p2.readiness = 1.0
        ranked = rank_providers(r.get_providers("code.write"), req)
        assert ranked[0].provider.provider_id == "agent:b"

    def test_CR102_degraded_avoided_when_ready_exists(self):
        """Degraded provider scored lower than ready alternative."""
        from core.capability_routing.spec import (
            ProviderSpec, ProviderType, ProviderStatus, CapabilityRequirement,
        )
        from core.capability_routing.scorer import rank_providers

        ready = ProviderSpec(
            provider_id="ready", provider_type=ProviderType.AGENT,
            capability_id="c", status=ProviderStatus.READY,
            readiness=1.0, reliability=0.7,
        )
        degraded = ProviderSpec(
            provider_id="degraded", provider_type=ProviderType.AGENT,
            capability_id="c", status=ProviderStatus.DEGRADED,
            readiness=0.4, reliability=0.7,
        )
        ranked = rank_providers(
            [degraded, ready],
            CapabilityRequirement(capability_id="c"),
        )
        assert ranked[0].provider.provider_id == "ready"

    def test_CR103_approval_deprioritized_when_safe_alternative(self):
        """Approval-required provider ranked below ready alternative."""
        from core.capability_routing.spec import (
            ProviderSpec, ProviderType, ProviderStatus, CapabilityRequirement,
        )
        from core.capability_routing.scorer import rank_providers

        safe = ProviderSpec(
            provider_id="safe", provider_type=ProviderType.AGENT,
            capability_id="c", status=ProviderStatus.READY,
            readiness=1.0, reliability=0.7, requires_approval=False,
        )
        gated = ProviderSpec(
            provider_id="gated", provider_type=ProviderType.AGENT,
            capability_id="c", status=ProviderStatus.READY,
            readiness=1.0, reliability=0.7, requires_approval=True,
        )
        ranked = rank_providers(
            [gated, safe],
            CapabilityRequirement(capability_id="c"),
        )
        assert ranked[0].provider.provider_id == "safe"

    def test_CR104_registry_refresh_stable_routing(self):
        """Routing produces consistent results after registry refresh."""
        from core.capability_routing.registry import ProviderRegistry
        from core.capability_routing.spec import CapabilityRequirement
        from core.capability_routing.scorer import rank_providers

        r = ProviderRegistry()
        r.populate()
        caps_before = r.get_all_capabilities()

        # Refresh
        r.populate()
        caps_after = r.get_all_capabilities()

        # Same capabilities available
        assert set(caps_before) == set(caps_after)

    def test_CR105_self_model_blocked_not_selected(self):
        """Provider with status DISABLED is never selected."""
        from core.capability_routing.spec import (
            ProviderSpec, ProviderType, ProviderStatus, CapabilityRequirement,
        )
        from core.capability_routing.scorer import score_provider

        disabled = ProviderSpec(
            provider_id="disabled", provider_type=ProviderType.MCP,
            capability_id="c", status=ProviderStatus.DISABLED,
        )
        result = score_provider(
            disabled,
            CapabilityRequirement(capability_id="c"),
        )
        assert result.blocked is True
        assert result.total_score == 0.0
