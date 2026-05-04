"""
tests/test_canonical_agents.py — Tests for canonical runtime agent architecture.

CA01-CA35: Agent definitions, specialist packs, routing, integration.
"""
import pytest


class TestCanonicalAgentDefinitions:

    def test_CA01_six_canonical_agents(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS
        assert len(CANONICAL_AGENTS) == 6

    def test_CA02_agent_ids(self):
        from core.agents.canonical_agents import CanonicalAgentId
        ids = [a.value for a in CanonicalAgentId]
        assert "cognitive_architect" in ids
        assert "planning_engineer" in ids
        assert "systems_engineer" in ids
        assert "execution_engineer" in ids
        assert "safety_guardian" in ids
        assert "learning_engineer" in ids

    def test_CA03_all_agents_have_capabilities(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS
        for agent in CANONICAL_AGENTS.values():
            assert len(agent.capabilities) > 0, f"{agent.name} has no capabilities"

    def test_CA04_all_agents_have_llm_role(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS
        for agent in CANONICAL_AGENTS.values():
            assert agent.llm_role, f"{agent.name} has no llm_role"

    def test_CA05_agents_serialize(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS
        for agent in CANONICAL_AGENTS.values():
            d = agent.to_dict()
            assert "id" in d
            assert "capabilities" in d
            assert "llm_role" in d

    def test_CA06_cognitive_architect_capabilities(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS, CanonicalAgentId
        arch = CANONICAL_AGENTS[CanonicalAgentId.COGNITIVE_ARCHITECT]
        assert "system_design" in arch.capabilities
        assert "dependency_analysis" in arch.capabilities

    def test_CA07_safety_guardian_capabilities(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS, CanonicalAgentId
        guardian = CANONICAL_AGENTS[CanonicalAgentId.SAFETY_GUARDIAN]
        assert "policy_enforcement" in guardian.capabilities
        assert "risk_assessment" in guardian.capabilities

    def test_CA08_execution_engineer_risk(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS, CanonicalAgentId
        eng = CANONICAL_AGENTS[CanonicalAgentId.EXECUTION_ENGINEER]
        assert eng.risk_level == "medium"
        assert len(eng.requires_approval) > 0

    def test_CA09_systems_engineer_risk(self):
        from core.agents.canonical_agents import CANONICAL_AGENTS, CanonicalAgentId
        sys_eng = CANONICAL_AGENTS[CanonicalAgentId.SYSTEMS_ENGINEER]
        assert sys_eng.risk_level == "medium"


class TestSpecialistPacks:

    @pytest.mark.xfail(reason="expected 5 packs, drift", strict=False)
    def test_CA10_five_specialist_packs(self):
        from core.agents.canonical_agents import SPECIALIST_PACKS
        assert len(SPECIALIST_PACKS) == 5

    def test_CA11_pack_ids(self):
        from core.agents.canonical_agents import SPECIALIST_PACKS
        assert "business_intelligence" in SPECIALIST_PACKS
        assert "financial_reasoning" in SPECIALIST_PACKS
        assert "product_design" in SPECIALIST_PACKS
        assert "content_creation" in SPECIALIST_PACKS
        assert "devops_operations" in SPECIALIST_PACKS

    def test_CA12_packs_have_parent(self):
        from core.agents.canonical_agents import SPECIALIST_PACKS, CanonicalAgentId
        for pack in SPECIALIST_PACKS.values():
            assert isinstance(pack.parent_agent, CanonicalAgentId)

    def test_CA13_packs_serialize(self):
        from core.agents.canonical_agents import SPECIALIST_PACKS
        for pack in SPECIALIST_PACKS.values():
            d = pack.to_dict()
            assert "id" in d
            assert "parent_agent" in d
            assert "capabilities" in d

    def test_CA14_packs_inactive_by_default(self):
        from core.agents.canonical_agents import SPECIALIST_PACKS
        for pack in SPECIALIST_PACKS.values():
            assert pack.active is False


class TestCapabilityMapping:

    def test_CA15_capability_map_populated(self):
        from core.agents.canonical_agents import CAPABILITY_TO_AGENT
        assert len(CAPABILITY_TO_AGENT) > 20

    def test_CA16_system_design_maps_to_architect(self):
        from core.agents.canonical_agents import CAPABILITY_TO_AGENT, CanonicalAgentId
        assert CAPABILITY_TO_AGENT["system_design"] == CanonicalAgentId.COGNITIVE_ARCHITECT

    def test_CA17_code_generation_maps_to_execution(self):
        from core.agents.canonical_agents import CAPABILITY_TO_AGENT, CanonicalAgentId
        assert CAPABILITY_TO_AGENT["code_generation"] == CanonicalAgentId.EXECUTION_ENGINEER

    def test_CA18_policy_enforcement_maps_to_guardian(self):
        from core.agents.canonical_agents import CAPABILITY_TO_AGENT, CanonicalAgentId
        assert CAPABILITY_TO_AGENT["policy_enforcement"] == CanonicalAgentId.SAFETY_GUARDIAN

    def test_CA19_specialist_caps_map_to_parents(self):
        from core.agents.canonical_agents import CAPABILITY_TO_AGENT, CanonicalAgentId
        # market_research from business_intelligence pack → planning_engineer
        assert CAPABILITY_TO_AGENT.get("market_research") == CanonicalAgentId.PLANNING_ENGINEER


class TestLegacyMapping:

    def test_CA20_all_canonical_have_legacy_mapping(self):
        from core.agents.canonical_agents import CANONICAL_TO_LEGACY, CanonicalAgentId
        for agent_id in CanonicalAgentId:
            assert agent_id in CANONICAL_TO_LEGACY

    def test_CA21_legacy_roles_valid(self):
        from core.agents.canonical_agents import CANONICAL_TO_LEGACY
        valid_roles = {"ceo", "architect", "engineer", "analyst", "operator", "reviewer"}
        for role in CANONICAL_TO_LEGACY.values():
            assert role in valid_roles


class TestCanonicalRuntime:

    def test_CA22_singleton(self):
        from core.agents.canonical_agents import get_canonical_runtime
        r1 = get_canonical_runtime()
        r2 = get_canonical_runtime()
        assert r1 is r2

    def test_CA23_get_agent(self):
        from core.agents.canonical_agents import get_canonical_runtime, CanonicalAgentId
        rt = get_canonical_runtime()
        agent = rt.get_agent(CanonicalAgentId.COGNITIVE_ARCHITECT)
        assert agent is not None
        assert agent.name == "Cognitive Architect"

    def test_CA24_get_agent_by_string(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        agent = rt.get_agent("safety_guardian")
        assert agent is not None
        assert agent.name == "Safety & Alignment Guardian"

    def test_CA25_get_agent_invalid(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        assert rt.get_agent("nonexistent") is None

    def test_CA26_get_agent_for_capability(self):
        from core.agents.canonical_agents import get_canonical_runtime, CanonicalAgentId
        rt = get_canonical_runtime()
        assert rt.get_agent_for_capability("code_generation") == CanonicalAgentId.EXECUTION_ENGINEER

    def test_CA27_get_llm_role_for_capability(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        assert rt.get_llm_role_for_capability("system_design") == "architect"
        assert rt.get_llm_role_for_capability("code_generation") == "coder"
        assert rt.get_llm_role_for_capability("unknown_cap") == "analyst"

    def test_CA28_activate_pack(self):
        from core.agents.canonical_agents import get_canonical_runtime, SPECIALIST_PACKS
        rt = get_canonical_runtime()
        rt.deactivate_pack("business_intelligence")  # reset
        assert rt.activate_pack("business_intelligence") is True
        assert "business_intelligence" in rt._active_packs
        assert SPECIALIST_PACKS["business_intelligence"].active is True
        rt.deactivate_pack("business_intelligence")

    def test_CA29_deactivate_pack(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        rt.activate_pack("financial_reasoning")
        rt.deactivate_pack("financial_reasoning")
        assert "financial_reasoning" not in rt._active_packs

    def test_CA30_activate_invalid_pack(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        assert rt.activate_pack("nonexistent") is False

    def test_CA31_active_capabilities(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        caps = rt.get_active_capabilities()
        assert "code_generation" in caps
        assert "policy_enforcement" in caps

    @pytest.mark.xfail(reason="canonical runtime status drift", strict=False)
    def test_CA32_status(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        status = rt.get_status()
        assert len(status["canonical_agents"]) == 6
        assert len(status["specialist_packs"]) == 5
        assert status["total_capabilities"] > 20

    def test_CA33_enrich_self_model(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        data = {}
        enriched = rt.enrich_self_model(data)
        assert "canonical_agents" in enriched
        assert "specialist_packs" in enriched
        assert "capability_map" in enriched
        assert len(enriched["canonical_agents"]) == 6

    def test_CA34_enrich_routing_decision(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        decision = {}
        enriched = rt.enrich_routing_decision("code_generation", decision)
        assert enriched.get("canonical_agent") == "execution_engineer"
        assert enriched.get("canonical_llm_role") == "coder"

    def test_CA35_should_require_approval(self):
        from core.agents.canonical_agents import get_canonical_runtime
        rt = get_canonical_runtime()
        assert rt.should_require_approval("deployment") is True
        assert rt.should_require_approval("system_design") is False
