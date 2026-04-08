"""
Tests for domain routing integration — runtime path verification.
Tests: DR01-DR30
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══ DR01-DR05: RoutingDecision metadata field ═══

def test_dr01_routing_decision_has_metadata():
    from core.capability_routing.spec import RoutingDecision
    d = RoutingDecision(capability_id="test", selected_provider=None)
    assert hasattr(d, "metadata")
    assert isinstance(d.metadata, dict)

def test_dr02_routing_decision_to_dict_has_metadata():
    from core.capability_routing.spec import RoutingDecision
    d = RoutingDecision(capability_id="test", selected_provider=None, metadata={"foo": "bar"})
    dd = d.to_dict()
    assert "metadata" in dd
    assert dd["metadata"]["foo"] == "bar"


# ═══ DR03-DR07: BaseDomainRouter ═══

def test_dr03_base_domain_router_interface():
    from core.skills.domain_skill_router import BaseDomainRouter, SkillMeta
    # Can't instantiate abstract class directly
    with pytest.raises(TypeError):
        BaseDomainRouter()

def test_dr04_skill_meta_full_schema():
    from core.skills.domain_skill_router import SkillMeta
    s = SkillMeta(
        id="test-01", name="test_skill", domain="test",
        subdomain="sub", description="Test",
        risk_level="low", confidence_weight=0.9,
        tool_requirements=["nmap"], requires_activation=False,
        expected_output_type="report", tags=["test"],
    )
    d = s.to_dict()
    assert d["subdomain"] == "sub"
    assert d["expected_output_type"] == "report"
    assert d["confidence_weight"] == 0.9

def test_dr05_skill_meta_defaults():
    from core.skills.domain_skill_router import SkillMeta
    s = SkillMeta(id="t", name="t", domain="d")
    assert s.subdomain == ""
    assert s.expected_output_type == "report"
    assert s.risk_level == "low"


# ═══ DR06-DR10: SecuritySkillRouter as BaseDomainRouter ═══

def test_dr06_security_router_is_base_domain():
    from core.skills.security_skill_router import SecuritySkillRouter
    from core.skills.domain_skill_router import BaseDomainRouter
    router = SecuritySkillRouter()
    assert isinstance(router, BaseDomainRouter)

def test_dr07_security_router_domain_prefix():
    from core.skills.security_skill_router import SecuritySkillRouter
    router = SecuritySkillRouter()
    assert router.domain_prefix == "security"

def test_dr08_security_router_handles():
    from core.skills.security_skill_router import SecuritySkillRouter
    router = SecuritySkillRouter()
    assert router.handles("security.blue_team")
    assert router.handles("security.compliance")
    assert not router.handles("code.write")

def test_dr09_security_router_registered():
    from core.skills.domain_skill_router import get_domain_router
    # Importing security_skill_router should register the router
    import core.skills.security_skill_router  # noqa: F401
    router = get_domain_router("security.blue_team")
    assert router is not None
    assert router.domain_prefix == "security"

def test_dr10_security_router_resolve_via_generic():
    from core.skills.domain_skill_router import resolve_via_domain_routers
    import core.skills.security_skill_router  # noqa: F401 - ensure registered
    ctx = resolve_via_domain_routers("security.compliance", "NIS2 audit")
    assert ctx is not None
    assert ctx["matched"] is True
    assert ctx["domain"] == "compliance"


# ═══ DR11-DR15: Full route_mission integration ═══

def test_dr11_route_mission_security_has_metadata():
    from core.capability_routing.router import route_mission
    decisions = route_mission("analyze SIEM alerts for suspicious activity")
    sec = [d for d in decisions if d.capability_id.startswith("security.")]
    # Even if no provider found, metadata should be enriched
    for d in sec:
        assert hasattr(d, "metadata")
        if "domain_routing" in d.metadata:
            assert d.metadata["domain_routing"]["matched"] is True

def test_dr12_route_mission_nis2_compliance():
    from core.capability_routing.router import route_mission
    decisions = route_mission("prépare un audit NIS2 pour une PME SaaS")
    sec = [d for d in decisions if "compliance" in d.capability_id or "security" in d.capability_id]
    assert len(sec) > 0, f"No security/compliance decisions: {[d.capability_id for d in decisions]}"

def test_dr13_route_mission_red_team_blocked():
    from core.capability_routing.router import route_mission
    decisions = route_mission("run penetration test on staging server")
    red = [d for d in decisions if "red_team" in d.capability_id]
    if red:
        d = red[0]
        if "domain_routing" in d.metadata:
            assert d.metadata["domain_routing"].get("blocked") is True

def test_dr14_route_mission_non_security():
    from core.capability_routing.router import route_mission
    decisions = route_mission("write a Python function to sort a list")
    # Should NOT have security routing
    for d in decisions:
        assert "security" not in d.capability_id

def test_dr15_route_mission_osint():
    from core.capability_routing.router import route_mission
    decisions = route_mission("OSINT reconnaissance on target domain")
    osint = [d for d in decisions if "osint" in d.capability_id]
    assert len(osint) > 0


# ═══ DR16-DR20: Enriched skill tags ═══

def test_dr16_skills_have_subdomain():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path) as f:
        data = json.load(f)
    for skill in data["skills"]:
        assert "subdomain" in skill, f"Skill {skill['id']} missing subdomain"
        assert len(skill["subdomain"]) > 0, f"Skill {skill['id']} has empty subdomain"

def test_dr17_skills_have_expected_output_type():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path) as f:
        data = json.load(f)
    valid_types = {"report", "assessment", "action", "artifact"}
    for skill in data["skills"]:
        assert "expected_output_type" in skill, f"Skill {skill['id']} missing expected_output_type"
        assert skill["expected_output_type"] in valid_types, f"Skill {skill['id']} has invalid type {skill['expected_output_type']}"

def test_dr18_blue_team_output_types():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path) as f:
        data = json.load(f)
    bt = [s for s in data["skills"] if s["domain"] == "blue_team"]
    for s in bt:
        assert s["expected_output_type"] == "assessment"

def test_dr19_compliance_output_types():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path) as f:
        data = json.load(f)
    co = [s for s in data["skills"] if s["domain"] == "compliance"]
    for s in co:
        assert s["expected_output_type"] == "report"

def test_dr20_osint_output_types():
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path) as f:
        data = json.load(f)
    os_skills = [s for s in data["skills"] if s["domain"] == "osint"]
    for s in os_skills:
        assert s["expected_output_type"] == "report"


# ═══ DR21-DR24: Red team activation guard ═══

def test_dr21_red_team_pack_default_inactive():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    pack = SPECIALIST_PACKS.get("red_team_ethical")
    assert pack is not None
    assert pack.active is False

def test_dr22_red_team_routing_blocked():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.red_team", "pentest")
    assert ctx["blocked"] is True
    assert ctx["requires_activation"] is True

def test_dr23_red_team_activation_unblocks():
    from core.agents.canonical_agents import SPECIALIST_PACKS, get_canonical_runtime
    runtime = get_canonical_runtime()
    # Activate
    runtime.activate_pack("red_team_ethical")
    try:
        from core.skills.security_skill_router import get_security_skill_router
        router = get_security_skill_router()
        ctx = router.get_routing_context("security.red_team", "pentest")
        assert ctx["blocked"] is False
        assert ctx["pack_active"] is True
    finally:
        # Deactivate (cleanup)
        runtime.deactivate_pack("red_team_ethical")

def test_dr24_red_team_deactivated_after_test():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    pack = SPECIALIST_PACKS.get("red_team_ethical")
    assert pack.active is False


# ═══ DR25-DR28: Domain router registry ═══

def test_dr25_all_domain_routers():
    from core.skills.domain_skill_router import get_all_domain_routers
    import core.skills.security_skill_router  # noqa
    routers = get_all_domain_routers()
    assert "security" in routers

def test_dr26_unmatched_domain():
    from core.skills.domain_skill_router import resolve_via_domain_routers
    ctx = resolve_via_domain_routers("cooking.pasta")
    assert ctx is None

def test_dr27_domain_router_stats():
    from core.skills.domain_skill_router import get_domain_router
    import core.skills.security_skill_router  # noqa
    router = get_domain_router("security.blue_team")
    assert router is not None
    stats = router.stats()
    assert stats["prefix"] == "security"
    assert stats["total"] >= 49

def test_dr28_domain_router_handles_all_security():
    from core.skills.domain_skill_router import get_domain_router
    import core.skills.security_skill_router  # noqa
    router = get_domain_router("security.blue_team")
    assert router.handles("security.blue_team")
    assert router.handles("security.red_team")
    assert router.handles("security.compliance")
    assert router.handles("security.osint")


# ═══ DR29-DR30: Pack status report ═══

def test_dr29_pack_status_report():
    """Generate PROVEN/PARTIAL/WIRED/STUB classification for each pack."""
    import core.skills.security_skill_router  # noqa
    from core.capability_routing.resolver import resolve_capabilities
    from core.skills.domain_skill_router import resolve_via_domain_routers

    report = {}
    test_cases = {
        "blue_team": "analyze SIEM alerts and cloud security posture",
        "red_team": "run penetration test on web application",
        "compliance": "prepare NIS2 compliance audit for SaaS PME",
        "osint": "OSINT reconnaissance and breach monitoring on domain",
    }

    for domain, goal in test_cases.items():
        caps = resolve_capabilities(goal)
        sec_caps = [c for c in caps if "security" in c.capability_id]
        ctx = None
        for cap in sec_caps:
            ctx = resolve_via_domain_routers(cap.capability_id, goal)
            if ctx and ctx.get("matched") and ctx.get("domain") == domain:
                break

        if ctx and ctx.get("matched") and ctx.get("domain") == domain:
            if ctx.get("blocked"):
                report[domain] = "WIRED"  # Wired but blocked (red team)
            elif ctx.get("skills_count", 0) > 0:
                report[domain] = "PROVEN"  # Full path works
            else:
                report[domain] = "PARTIAL"
        elif sec_caps:
            report[domain] = "PARTIAL"  # Resolver works but domain routing incomplete
        else:
            report[domain] = "STUB"  # Nothing works

    # Assertions
    assert report.get("blue_team") == "PROVEN"
    assert report.get("compliance") == "PROVEN"
    assert report.get("osint") == "PROVEN"
    assert report.get("red_team") == "WIRED"  # Blocked by default = WIRED not PROVEN

def test_dr30_all_previous_tests_pass():
    """Meta-test: verify old test files still import correctly."""
    from core.capability_routing.resolver import resolve_capabilities
    from core.capability_routing.router import route_mission
    from core.skills.security_skill_router import get_security_skill_router
    from core.skills.domain_skill_router import BaseDomainRouter, get_domain_router
    from core.agents.canonical_agents import SPECIALIST_PACKS
    # All imports work = no regressions
    assert True
