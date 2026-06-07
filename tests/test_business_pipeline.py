"""
Business Pipeline Tests
==========================
Lead tracking, content pipeline, budget, dashboard, wiring.
"""
import ast
import sys
import time
import types

if 'structlog' not in sys.modules:
    sl = types.ModuleType('structlog')
    class ML:
        def info(self,*a,**k): pass
        def debug(self,*a,**k): pass
        def warning(self,*a,**k): pass
        def error(self,*a,**k): pass
    sl.get_logger = lambda *a,**k: ML()
    sys.modules['structlog'] = sl

sys.path.insert(0, '.')


# ═══════════════════════════════════════════════════════════════
# LEAD TRACKER
# ═══════════════════════════════════════════════════════════════

def test_add_lead():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_{int(time.time()*1000)}.json")
    lead = lt.add_lead("Acme Corp", source="cold_outreach", value_estimate=5000,
                       tags=["saas", "b2b"], notes="Potential client for automation")
    assert lead.lead_id
    assert lead.stage == "lead"
    assert lead.value_estimate == 5000


def test_advance_lead():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_adv_{int(time.time()*1000)}.json")
    lead = lt.add_lead("TechStart Inc", value_estimate=3000)
    lt.advance_lead(lead.lead_id, "qualified", "Fits our ICP")
    lt.advance_lead(lead.lead_id, "proposal_sent", "Proposal delivered")
    updated = lt.get_lead(lead.lead_id)
    assert updated.stage == "proposal_sent"
    assert len(updated.stage_history) == 3  # lead→qualified→proposal_sent


def test_lead_invalid_stage():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_inv_{int(time.time()*1000)}.json")
    lead = lt.add_lead("BadStage Co")
    result = lt.advance_lead(lead.lead_id, "nonexistent_stage")
    assert result is None


def test_lead_pipeline_summary():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_sum_{int(time.time()*1000)}.json")
    lt.add_lead("A", value_estimate=1000)
    lt.add_lead("B", value_estimate=2000)
    lead_c = lt.add_lead("C", value_estimate=3000)
    lt.advance_lead(lead_c.lead_id, "qualified")
    lt.advance_lead(lead_c.lead_id, "active")

    summary = lt.get_pipeline_summary()
    assert summary["total_leads"] == 3
    assert summary["active_leads"] == 3  # none closed/lost
    assert summary["total_pipeline_value"] == 6000


def test_lead_conversion_rate():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_conv_{int(time.time()*1000)}.json")
    for i in range(4):
        lead = lt.add_lead(f"Lead_{i}")
        if i < 2:
            lt.advance_lead(lead.lead_id, "delivered")
        else:
            lt.advance_lead(lead.lead_id, "lost")

    summary = lt.get_pipeline_summary()
    assert summary["won"] == 2
    assert summary["lost"] == 2
    assert summary["conversion_rate"] == 0.5


def test_lead_persistence():
    from core.business_pipeline import LeadTracker
    path = f"/tmp/bea_leads_pers_{int(time.time()*1000)}.json"
    lt1 = LeadTracker(persist_path=path)
    lt1.add_lead("Persistent Lead", value_estimate=999)

    lt2 = LeadTracker(persist_path=path)
    lt2._ensure_loaded()
    assert len(lt2._leads) == 1
    lead = list(lt2._leads.values())[0]
    assert lead.name == "Persistent Lead"
    assert lead.value_estimate == 999


def test_lead_update():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_upd_{int(time.time()*1000)}.json")
    lead = lt.add_lead("Update Test", value_estimate=100)
    lt.update_lead(lead.lead_id, value_estimate=500, notes="Revised estimate")
    updated = lt.get_lead(lead.lead_id)
    assert updated.value_estimate == 500
    assert updated.notes == "Revised estimate"


def test_lead_bounded():
    from core.business_pipeline import LeadTracker, MAX_LEADS
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_bound_{int(time.time()*1000)}.json")
    lt._loaded = True
    # Fill with closed leads (evictable)
    for i in range(MAX_LEADS):
        lead = lt.add_lead(f"Lead_{i}")
        lt.advance_lead(lead.lead_id, "closed")
    # Should evict oldest closed, not fail
    new_lead = lt.add_lead("New Lead")
    assert new_lead.lead_id
    assert len(lt._leads) <= MAX_LEADS


def test_lead_list_filtering():
    from core.business_pipeline import LeadTracker
    lt = LeadTracker(persist_path=f"/tmp/bea_leads_filt_{int(time.time()*1000)}.json")
    lt.add_lead("A", tags=["saas"])
    lt.add_lead("B", tags=["ecom"])
    lead_c = lt.add_lead("C", tags=["saas"])
    lt.advance_lead(lead_c.lead_id, "qualified")

    saas = lt.list_leads(tag="saas")
    assert len(saas) == 2
    qualified = lt.list_leads(stage="qualified")
    assert len(qualified) == 1


# ═══════════════════════════════════════════════════════════════
# CONTENT PIPELINE
# ═══════════════════════════════════════════════════════════════

def test_create_content():
    from core.business_pipeline import ContentPipeline
    cp = ContentPipeline(persist_path=f"/tmp/bea_content_{int(time.time()*1000)}.json")
    item = cp.create("How to Automate X", content_type="article",
                     body="Introduction to automation...", tags=["automation"])
    assert item.content_id
    assert item.stage == "idea"
    assert item.word_count > 0


def test_content_advance():
    from core.business_pipeline import ContentPipeline
    cp = ContentPipeline(persist_path=f"/tmp/bea_content_adv_{int(time.time()*1000)}.json")
    item = cp.create("Blog Post", body="Draft content here")
    cp.advance(item.content_id, "draft")
    cp.advance(item.content_id, "review")
    updated = cp.get(item.content_id)
    assert updated.stage == "review"
    assert len(updated.stage_history) == 3


def test_content_update_body():
    from core.business_pipeline import ContentPipeline
    cp = ContentPipeline(persist_path=f"/tmp/bea_content_body_{int(time.time()*1000)}.json")
    item = cp.create("Draft Post")
    cp.update_body(item.content_id, "This is the full content with more words now")
    updated = cp.get(item.content_id)
    assert updated.word_count > 0
    assert "full content" in updated.body


def test_content_summary():
    from core.business_pipeline import ContentPipeline
    cp = ContentPipeline(persist_path=f"/tmp/bea_content_sum_{int(time.time()*1000)}.json")
    cp.create("A", content_type="article")
    cp.create("B", content_type="proposal")
    item_c = cp.create("C", content_type="article")
    cp.advance(item_c.content_id, "published")

    summary = cp.get_summary()
    assert summary["total"] == 3
    assert summary["by_type"]["article"] == 2
    assert summary["by_stage"]["published"] == 1


def test_content_persistence():
    from core.business_pipeline import ContentPipeline
    path = f"/tmp/bea_content_pers_{int(time.time()*1000)}.json"
    cp1 = ContentPipeline(persist_path=path)
    cp1.create("Persistent Article", body="Content here")

    cp2 = ContentPipeline(persist_path=path)
    cp2._ensure_loaded()
    assert len(cp2._items) == 1


# ═══════════════════════════════════════════════════════════════
# BUDGET TRACKER
# ═══════════════════════════════════════════════════════════════

def test_budget_record():
    from core.business_pipeline import BudgetTracker
    bt = BudgetTracker(persist_path=f"/tmp/bea_budget_{int(time.time()*1000)}.jsonl")
    entry = bt.record("api_cost", -5.50, "OpenAI API calls")
    assert entry.amount == -5.50
    assert entry.category == "api_cost"


def test_budget_summary():
    from core.business_pipeline import BudgetTracker
    bt = BudgetTracker(persist_path=f"/tmp/bea_budget_sum_{int(time.time()*1000)}.jsonl")
    bt.record("revenue", 100.0, "Client payment", objective_id="obj-1")
    bt.record("api_cost", -20.0, "LLM costs", objective_id="obj-1")
    bt.record("tool_cost", -5.0, "Hosting")

    summary = bt.get_summary()
    assert summary["total_revenue"] == 100.0
    assert summary["total_cost"] == 25.0
    assert summary["net"] == 75.0
    assert summary["roi"] > 1.0
    assert "obj-1" in summary["by_objective"]


def test_budget_per_objective():
    from core.business_pipeline import BudgetTracker
    bt = BudgetTracker(persist_path=f"/tmp/bea_budget_obj_{int(time.time()*1000)}.jsonl")
    bt.record("revenue", 500.0, "Sale", objective_id="proj-a")
    bt.record("api_cost", -50.0, "Costs", objective_id="proj-a")
    bt.record("revenue", 200.0, "Sale", objective_id="proj-b")

    summary = bt.get_summary(objective_id="proj-a")
    assert summary["total_revenue"] == 500.0
    assert summary["total_cost"] == 50.0


def test_budget_bounded():
    from core.business_pipeline import BudgetTracker, MAX_BUDGET_ENTRIES
    bt = BudgetTracker(persist_path=f"/tmp/bea_budget_bound_{int(time.time()*1000)}.jsonl")
    bt._loaded = True
    for i in range(MAX_BUDGET_ENTRIES + 100):
        bt.record("test", -0.01, f"Entry {i}")
    assert len(bt._entries) <= MAX_BUDGET_ENTRIES


def test_budget_persistence():
    from core.business_pipeline import BudgetTracker
    path = f"/tmp/bea_budget_pers_{int(time.time()*1000)}.jsonl"
    bt1 = BudgetTracker(persist_path=path)
    bt1.record("revenue", 42.0, "Test")

    bt2 = BudgetTracker(persist_path=path)
    bt2._ensure_loaded()
    assert len(bt2._entries) == 1
    assert bt2._entries[0].amount == 42.0


# ═══════════════════════════════════════════════════════════════
# BUSINESS DASHBOARD
# ═══════════════════════════════════════════════════════════════

def test_business_dashboard():
    from core.business_pipeline import (
        LeadTracker, ContentPipeline, BudgetTracker, get_business_dashboard,
    )
    lt = LeadTracker(persist_path=f"/tmp/bea_bd_leads_{int(time.time()*1000)}.json")
    cp = ContentPipeline(persist_path=f"/tmp/bea_bd_content_{int(time.time()*1000)}.json")
    bt = BudgetTracker(persist_path=f"/tmp/bea_bd_budget_{int(time.time()*1000)}.jsonl")

    lt.add_lead("Test Client", value_estimate=1000)
    cp.create("Test Article")
    bt.record("revenue", 100.0, "Sale")

    dashboard = get_business_dashboard(lt, cp, bt)
    assert "pipeline" in dashboard
    assert "content" in dashboard
    assert "budget" in dashboard
    assert "health_score" in dashboard
    assert "actions_needed" in dashboard
    assert dashboard["health_score"] > 0


def test_actions_detection():
    from core.business_pipeline import (
        LeadTracker, ContentPipeline, BudgetTracker, get_business_dashboard,
    )
    # Empty pipeline → should suggest prospecting
    lt = LeadTracker(persist_path=f"/tmp/bea_bd_act_{int(time.time()*1000)}.json")
    cp = ContentPipeline(persist_path=f"/tmp/bea_bd_act_c_{int(time.time()*1000)}.json")
    bt = BudgetTracker(persist_path=f"/tmp/bea_bd_act_b_{int(time.time()*1000)}.jsonl")

    dashboard = get_business_dashboard(lt, cp, bt)
    actions = dashboard["actions_needed"]
    assert any(a["action"] == "prospecting" for a in actions)


# ═══════════════════════════════════════════════════════════════
# FULL BUSINESS WORKFLOW SCENARIO
# ═══════════════════════════════════════════════════════════════

def test_scenario_full_business_cycle():
    """Complete business cycle: lead → qualify → proposal → deliver → revenue."""
    from core.business_pipeline import LeadTracker, ContentPipeline, BudgetTracker

    lt = LeadTracker(persist_path=f"/tmp/bea_cycle_leads_{int(time.time()*1000)}.json")
    cp = ContentPipeline(persist_path=f"/tmp/bea_cycle_content_{int(time.time()*1000)}.json")
    bt = BudgetTracker(persist_path=f"/tmp/bea_cycle_budget_{int(time.time()*1000)}.jsonl")

    # 1. New lead comes in
    lead = lt.add_lead("BigCo", source="inbound", value_estimate=10000, tags=["enterprise"])

    # 2. Qualify
    lt.advance_lead(lead.lead_id, "qualified", "Fits ICP, budget confirmed")

    # 3. Create and advance proposal
    proposal = cp.create(
        "BigCo Automation Proposal",
        content_type="proposal",
        body="We propose a 3-phase automation project...",
        lead_id=lead.lead_id,
    )
    cp.advance(proposal.content_id, "draft")
    cp.advance(proposal.content_id, "review")
    cp.advance(proposal.content_id, "published")

    # 4. Send proposal
    lt.advance_lead(lead.lead_id, "proposal_sent", "Proposal delivered via email")

    # 5. Negotiate and win
    lt.advance_lead(lead.lead_id, "negotiation")
    lt.advance_lead(lead.lead_id, "active", "Contract signed")

    # 6. Track costs during delivery
    bt.record("tool_cost", -50.0, "API costs for BigCo project", lead_id=lead.lead_id)
    bt.record("time_cost", -200.0, "20h @ $10/h", lead_id=lead.lead_id)

    # 7. Deliver
    lt.advance_lead(lead.lead_id, "delivered", "All deliverables accepted")

    # 8. Revenue
    bt.record("revenue", 10000.0, "BigCo payment", lead_id=lead.lead_id)

    # 9. Close
    lt.advance_lead(lead.lead_id, "closed")

    # Verify end state
    final = lt.get_lead(lead.lead_id)
    assert final.stage == "closed"
    assert len(final.stage_history) == 7  # initial(lead) + 6 advances

    summary = bt.get_summary()
    assert summary["net"] > 0
    assert summary["total_revenue"] == 10000.0


# ═══════════════════════════════════════════════════════════════
# ARCHITECTURE
# ═══════════════════════════════════════════════════════════════

def test_no_orchestration_in_business_pipeline():
    with open("core/business_pipeline.py", encoding="utf-8") as f:
        src = f.read()
    assert "MissionSystem" not in src
    assert "MetaOrchestrator" not in src
    assert "lifecycle_tracker" not in src
    ast.parse(src)


def test_api_has_business_endpoints():
    with open("api/routes/performance.py", encoding="utf-8") as f:
        src = f.read()
    assert "/business/dashboard" in src
    assert "/business/leads" in src
    assert "/business/content" in src
    assert "/business/budget" in src


def test_mission_system_wires_budget():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "get_budget_tracker" in src
    assert "mission_cost" in src


def test_mission_system_wires_events():
    with open("core/mission_system.py", encoding="utf-8") as f:
        src = f.read()
    assert "get_event_manager" in src
    assert "mission_completed" in src


def test_all_files_parse():
    for f in ["core/business_pipeline.py", "core/mission_system.py", "api/routes/performance.py"]:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
