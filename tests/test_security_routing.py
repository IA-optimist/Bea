"""
Tests for security skill routing — resolver patterns and SecuritySkillRouter.
Tests: SR01-SR30
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══ SR01-SR05: Resolver patterns for security domains ═══

def test_sr01_blue_team_siem():
    from core.capability_routing.resolver import resolve_capabilities
    caps = resolve_capabilities("analyze SIEM alerts for suspicious activity")
    cap_ids = [c.capability_id for c in caps]
    assert any("security" in cid for cid in cap_ids)

def test_sr02_blue_team_cloud_security():
    from core.capability_routing.resolver import resolve_capabilities
    caps = resolve_capabilities("review cloud security posture on AWS")
    cap_ids = [c.capability_id for c in caps]
    assert any("security" in cid for cid in cap_ids)

def test_sr03_red_team_pentest():
    from core.capability_routing.resolver import resolve_capabilities
    caps = resolve_capabilities("run penetration test on staging environment")
    cap_ids = [c.capability_id for c in caps]
    assert any("red_team" in cid or "security" in cid for cid in cap_ids)

def test_sr04_compliance_nis2():
    from core.capability_routing.resolver import resolve_capabilities
    caps = resolve_capabilities("prepare NIS2 compliance audit")
    cap_ids = [c.capability_id for c in caps]
    assert any("compliance" in cid or "security" in cid for cid in cap_ids)

def test_sr05_osint_recon():
    from core.capability_routing.resolver import resolve_capabilities
    caps = resolve_capabilities("OSINT reconnaissance on target domain")
    cap_ids = [c.capability_id for c in caps]
    assert any("osint" in cid or "security" in cid for cid in cap_ids)


# ═══ SR06-SR10: SecuritySkillRouter loading and stats ═══

def test_sr06_router_loads():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    assert router._loaded is True
    assert len(router._skills) >= 49

def test_sr07_router_stats():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    stats = router.stats()
    assert stats["total"] >= 49
    assert "blue_team" in stats["by_domain"]
    assert "red_team" in stats["by_domain"]
    assert "compliance" in stats["by_domain"]
    assert "osint" in stats["by_domain"]

def test_sr08_router_skill_tags():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    for skill in router._skills.values():
        assert len(skill.tags) > 0, f"Skill {skill.id} has no tags"

def test_sr09_red_team_skill_requires_activation():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    red_skills = [s for s in router._skills.values() if s.domain == "red_team"]
    for s in red_skills:
        assert s.requires_activation is True, f"Red team skill {s.id} should require activation"

def test_sr10_tool_requirements_populated():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    has_tools = sum(1 for s in router._skills.values() if len(s.tool_requirements) > 0)
    assert has_tools >= 30, f"Only {has_tools} skills have tool requirements"


# ═══ SR11-SR15: Domain resolution ═══

def test_sr11_resolve_blue_team_domain():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.blue_team")
    assert len(skills) > 0
    assert all(s.domain == "blue_team" for s in skills)

def test_sr12_resolve_red_team_domain():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.red_team")
    assert len(skills) > 0
    assert all(s.domain == "red_team" for s in skills)

def test_sr13_resolve_compliance_domain():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.compliance")
    assert len(skills) > 0
    assert all(s.domain == "compliance" for s in skills)

def test_sr14_resolve_osint_domain():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.osint")
    assert len(skills) > 0
    assert all(s.domain == "osint" for s in skills)

def test_sr15_resolve_unknown_capability():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.nonexistent")
    assert len(skills) == 0


# ═══ SR16-SR20: Routing context ═══

def test_sr16_routing_context_blue_team():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.blue_team", "analyze SIEM alerts")
    assert ctx["matched"] is True
    assert ctx["domain"] == "blue_team"
    assert ctx["blocked"] is False

def test_sr17_routing_context_red_team_blocked():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.red_team", "pentest")
    assert ctx["matched"] is True
    assert ctx["domain"] == "red_team"
    assert ctx["blocked"] is True
    assert ctx["requires_activation"] is True

def test_sr18_routing_context_compliance():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.compliance", "NIS2 audit")
    assert ctx["matched"] is True
    assert ctx["domain"] == "compliance"
    assert ctx["specialist_pack"] == "nis2_compliance"

def test_sr19_routing_context_unmatched():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.nonexistent", "unknown")
    assert ctx["matched"] is False

def test_sr20_routing_context_top_skills():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    ctx = router.get_routing_context("security.blue_team", "SIEM alert analysis")
    assert ctx["skills_count"] > 0
    assert len(ctx["top_skills"]) > 0
    assert len(ctx["top_skills"]) <= 5


# ═══ SR21-SR25: Keyword scoring ═══

def test_sr21_keyword_scoring_siem():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.blue_team", "SIEM alert analysis and correlation")
    assert len(skills) > 0
    # siem_alert_analysis should be ranked highly
    top_names = [s.name for s in skills[:3]]
    assert any("siem" in n for n in top_names)

def test_sr22_keyword_scoring_nis2():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.compliance", "NIS2 gap analysis for SaaS company")
    assert len(skills) > 0
    top_names = [s.name for s in skills[:3]]
    assert any("nis2" in n for n in top_names)

def test_sr23_keyword_scoring_domain_recon():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.osint", "domain reconnaissance and DNS enumeration")
    assert len(skills) > 0
    top_names = [s.name for s in skills[:3]]
    assert any("domain" in n or "recon" in n for n in top_names)

def test_sr24_keyword_scoring_pentest():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills = router.resolve("security.red_team", "web application penetration test")
    assert len(skills) > 0
    top_names = [s.name for s in skills[:3]]
    assert any("web" in n or "pentest" in n for n in top_names)

def test_sr25_no_goal_returns_all_domain():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    skills_with_goal = router.resolve("security.blue_team", "some specific goal")
    skills_no_goal = router.resolve("security.blue_team")
    # Both should return same count (all skills in domain)
    assert len(skills_with_goal) == len(skills_no_goal)


# ═══ SR26-SR30: End-to-end flows ═══

def test_sr26_e2e_cloud_security_to_blue_team():
    from core.capability_routing.resolver import resolve_capabilities
    from core.skills.security_skill_router import get_security_skill_router
    caps = resolve_capabilities("review cloud security posture on AWS and Azure")
    sec_caps = [c for c in caps if c.capability_id.startswith("security.")]
    assert len(sec_caps) > 0

    router = get_security_skill_router()
    for cap in sec_caps:
        ctx = router.get_routing_context(cap.capability_id, "cloud security posture")
        if ctx.get("matched") and ctx.get("domain") == "blue_team":
            assert ctx["skills_count"] > 0
            break
    else:
        pytest.fail("No blue_team match found for cloud security goal")

def test_sr27_e2e_nis2_to_compliance():
    from core.capability_routing.resolver import resolve_capabilities
    from core.skills.security_skill_router import get_security_skill_router
    caps = resolve_capabilities("prepare NIS2 compliance gap analysis")
    sec_caps = [c for c in caps if c.capability_id.startswith("security.")]
    assert len(sec_caps) > 0

    router = get_security_skill_router()
    for cap in sec_caps:
        ctx = router.get_routing_context(cap.capability_id, "NIS2 gap analysis")
        if ctx.get("matched") and ctx.get("domain") == "compliance":
            assert ctx["skills_count"] > 0
            break
    else:
        pytest.fail("No compliance match found for NIS2 goal")

def test_sr28_e2e_pentest_to_red_team_blocked():
    from core.capability_routing.resolver import resolve_capabilities
    from core.skills.security_skill_router import get_security_skill_router
    caps = resolve_capabilities("run penetration test on web application")
    sec_caps = [c for c in caps if c.capability_id.startswith("security.")]
    assert len(sec_caps) > 0

    router = get_security_skill_router()
    for cap in sec_caps:
        ctx = router.get_routing_context(cap.capability_id, "penetration test")
        if ctx.get("matched") and ctx.get("domain") == "red_team":
            assert ctx["blocked"] is True
            break
    else:
        pytest.fail("No red_team match found for pentest goal")

def test_sr29_e2e_osint_recon_to_osint():
    from core.capability_routing.resolver import resolve_capabilities
    from core.skills.security_skill_router import get_security_skill_router
    caps = resolve_capabilities("OSINT reconnaissance on target domain")
    sec_caps = [c for c in caps if c.capability_id.startswith("security.")]
    assert len(sec_caps) > 0

    router = get_security_skill_router()
    for cap in sec_caps:
        ctx = router.get_routing_context(cap.capability_id, "OSINT reconnaissance")
        if ctx.get("matched") and ctx.get("domain") == "osint":
            assert ctx["skills_count"] > 0
            break
    else:
        pytest.fail("No osint match found for OSINT recon goal")

def test_sr30_e2e_all_domains_have_skills():
    from core.skills.security_skill_router import get_security_skill_router
    router = get_security_skill_router()
    for domain_cap in ["security.blue_team", "security.red_team", "security.compliance", "security.osint"]:
        skills = router.resolve(domain_cap)
        assert len(skills) >= 10, f"{domain_cap} has only {len(skills)} skills"
