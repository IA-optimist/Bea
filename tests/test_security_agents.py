"""
Tests for security agent packs and skill catalog.
Tests: SA01-SA35
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══ SA01-SA04: Security specialist packs exist ═══

def test_sa01_blue_team_pack_exists():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert "blue_team" in SPECIALIST_PACKS

def test_sa02_red_team_pack_exists():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert "red_team_ethical" in SPECIALIST_PACKS

def test_sa03_nis2_compliance_pack_exists():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert "nis2_compliance" in SPECIALIST_PACKS

def test_sa04_osint_legal_pack_exists():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert "osint_legal" in SPECIALIST_PACKS


# ═══ SA05-SA08: Pack serialization ═══

def test_sa05_blue_team_to_dict():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    d = SPECIALIST_PACKS["blue_team"].to_dict()
    assert d["id"] == "blue_team"
    assert "capabilities" in d

def test_sa06_red_team_to_dict():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    d = SPECIALIST_PACKS["red_team_ethical"].to_dict()
    assert d["id"] == "red_team_ethical"

def test_sa07_nis2_to_dict():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    d = SPECIALIST_PACKS["nis2_compliance"].to_dict()
    assert d["id"] == "nis2_compliance"

def test_sa08_osint_to_dict():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    d = SPECIALIST_PACKS["osint_legal"].to_dict()
    assert d["id"] == "osint_legal"


# ═══ SA09-SA12: Pack capabilities count ═══

def test_sa09_blue_team_capabilities_count():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert len(SPECIALIST_PACKS["blue_team"].capabilities) >= 5

def test_sa10_red_team_capabilities_count():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert len(SPECIALIST_PACKS["red_team_ethical"].capabilities) >= 5

def test_sa11_nis2_capabilities_count():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert len(SPECIALIST_PACKS["nis2_compliance"].capabilities) >= 5

def test_sa12_osint_capabilities_count():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    assert len(SPECIALIST_PACKS["osint_legal"].capabilities) >= 5


# ═══ SA13-SA16: Pack parent agent ═══

def test_sa13_blue_team_parent():
    from core.agents.canonical_agents import SPECIALIST_PACKS, CanonicalAgentId
    assert SPECIALIST_PACKS["blue_team"].parent_agent == CanonicalAgentId.SAFETY_GUARDIAN

def test_sa14_red_team_parent():
    from core.agents.canonical_agents import SPECIALIST_PACKS, CanonicalAgentId
    assert SPECIALIST_PACKS["red_team_ethical"].parent_agent == CanonicalAgentId.SAFETY_GUARDIAN

def test_sa15_nis2_parent():
    from core.agents.canonical_agents import SPECIALIST_PACKS, CanonicalAgentId
    assert SPECIALIST_PACKS["nis2_compliance"].parent_agent == CanonicalAgentId.SAFETY_GUARDIAN

def test_sa16_osint_parent():
    from core.agents.canonical_agents import SPECIALIST_PACKS, CanonicalAgentId
    assert SPECIALIST_PACKS["osint_legal"].parent_agent == CanonicalAgentId.SAFETY_GUARDIAN


# ═══ SA17-SA20: Skill catalog file validation ═══

def test_sa17_skills_file_exists():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    assert os.path.exists(path)

def test_sa18_skills_file_valid_json():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "skills" in data
    assert isinstance(data["skills"], list)

def test_sa19_skills_count_50():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert 47 <= len(data["skills"]) <= 50

def test_sa20_skills_all_have_required_fields():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for skill in data["skills"]:
        assert "id" in skill
        assert "name" in skill
        assert "domain" in skill
        assert "description" in skill


# ═══ SA21-SA24: Skills per domain ═══

def test_sa21_blue_team_skills_count():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    bt = [s for s in data["skills"] if s["domain"] == "blue_team"]
    assert len(bt) >= 10

def test_sa22_red_team_skills_count():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rt = [s for s in data["skills"] if s["domain"] == "red_team"]
    assert len(rt) >= 10

def test_sa23_compliance_skills_count():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    co = [s for s in data["skills"] if s["domain"] == "compliance"]
    assert len(co) >= 10

def test_sa24_osint_skills_count():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    os_skills = [s for s in data["skills"] if s["domain"] == "osint"]
    assert len(os_skills) >= 10


# ═══ SA25-SA28: Skill metadata quality ═══

def test_sa25_skill_ids_unique():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ids = [s["id"] for s in data["skills"]]
    assert len(ids) == len(set(ids))

def test_sa26_skill_ids_format():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for skill in data["skills"]:
        parts = skill["id"].split("-")
        assert len(parts) == 2
        assert parts[0] in ("bt", "rt", "co", "os")
        assert parts[1].isdigit()

def test_sa27_domain_values_valid():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    valid_domains = {"blue_team", "red_team", "compliance", "osint"}
    for skill in data["skills"]:
        assert skill["domain"] in valid_domains

def test_sa28_descriptions_not_empty():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "skill.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for skill in data["skills"]:
        assert len(skill["description"]) > 10


# ═══ SA29-SA30: MCP integration ═══

def test_sa29_context7_mcp_registered():
    from core.mcp.mcp_registry import _CORE_MCP_STACK
    ids = [e.id for e in _CORE_MCP_STACK]
    assert "mcp-context7" in ids

def test_sa30_context7_mcp_fields():
    from core.mcp.mcp_registry import _CORE_MCP_STACK
    entry = next(e for e in _CORE_MCP_STACK if e.id == "mcp-context7")
    assert all(hasattr(entry, f) for f in ("name", "description", "transport", "tags"))


# ═══ SA31-SA35: Pack integration and files ═══

def test_sa31_all_packs_have_parent():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    for pack in SPECIALIST_PACKS.values():
        assert pack.parent_agent is not None

def test_sa32_no_capability_overlap_security_packs():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    security_packs = ["blue_team", "red_team_ethical", "nis2_compliance", "osint_legal"]
    all_caps = []
    for pid in security_packs:
        pack = SPECIALIST_PACKS[pid]
        all_caps.extend(pack.capabilities)
    # Allow some overlap but no full duplicate sets
    assert len(all_caps) == len(set(all_caps)), "Duplicate capabilities across security packs"

def test_sa33_total_specialist_packs_count():
    from core.agents.canonical_agents import SPECIALIST_PACKS
    # Original 5 + 4 security = 9
    assert len(SPECIALIST_PACKS) >= 9

def test_sa34_evaluation_file_exists():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "evaluation.md")
    assert os.path.exists(path)

def test_sa35_logic_file_exists():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "business", "skills", "cybersecurity", "logic.md")
    assert os.path.exists(path)
