# Bea First Euros Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Bea into a repeatable B2B launch machine that produces a sellable offer, a sales landing page, an outreach sequence, and a first-paid-pilot launch bundle.

**Architecture:** Keep one revenue offer as the source of truth, generate the launch assets from deterministic business data, and wire that bundle into the existing business executor so Bea can keep producing a complete sales package even when LLM output is empty. The first offer is productized service first, SaaS later: `InvoiceOps Guard` for SaaS B2B teams that need to detect revenue leaks before customers churn or billing errors compound.

**Tech Stack:** Python, existing Bea business agents, `core/business_actions.py`, `workspace/business/*` artifacts, pytest.

---

### Task 1: Add a revenue launch package action

**Files:**
- Modify: `core/business_actions.py`
- Create: `tests/test_business_revenue_launch.py`

- [ ] **Step 1: Write the failing test**

```python
def test_revenue_launch_package_creates_sales_bundle(tmp_path, monkeypatch):
    from core.business_actions import get_business_executor

    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    executor = get_business_executor()

    payload = {
        "product_name": "InvoiceOps Guard",
        "source": "InvoiceOps Guard",
        "recommended": "InvoiceOps Guard",
        "offers": [
            {
                "title": "InvoiceOps Guard",
                "tagline": "Detect revenue leaks before they become churn.",
                "problem_statement": "SaaS teams lose money on billing mistakes and renewal leaks.",
                "value_proposition": "A fast audit plus a clear remediation plan.",
                "target_persona": "Founder / Ops lead in a 5-50 person SaaS",
                "offer_type": "productized",
                "delivery_mode": "Audit + report + follow-up",
                "key_features": ["Audit", "Report", "Action plan"],
                "differentiators": ["Focused on revenue leaks", "Fast turnaround"],
                "objection_answers": {"Too expensive": "Cheaper than revenue loss."},
                "pricing_tiers": [{"name": "Audit", "price_month": 0, "price_year": 0, "description": "One-time audit", "ideal_for": "Pilot"}],
                "monetization_model": "Fixed-fee audit then monthly retainer",
                "upsell_path": "Audit -> monthly monitoring retainer",
                "landing_headline": "Stop leaking SaaS revenue",
                "cta": "Book a revenue leak audit",
                "sales_script_opener": "Can I show you where revenue is leaking?",
            }
        ],
        "synthesis": "Revenue leak audit for SaaS B2B.",
    }

    result = executor.execute("revenue.launch_package", payload, mission_id="m1", project_name="InvoiceOps Guard")

    assert result["ok"] is True
    assert "landing/index.html" in result["files_created"]
    assert "outreach.md" in result["files_created"]
    assert "qualification.md" in result["files_created"]
```

- [ ] **Step 2: Run the new test and verify it fails**

Run: `python -m pytest tests/test_business_revenue_launch.py -q`
Expected: fail with `Unknown action: revenue.launch_package`

- [ ] **Step 3: Implement the minimal action**

Add a new `BusinessAction` entry for `revenue.launch_package` with expected outputs:
`README.md`, `offer.md`, `landing/index.html`, `outreach.md`, `qualification.md`, `next-steps.md`.

Add a new handler in `BusinessActionExecutor` that writes those files from the structured payload, using the `InvoiceOps Guard` offer as default when the payload is thin.

- [ ] **Step 4: Run the test and verify it passes**

Run: `python -m pytest tests/test_business_revenue_launch.py -q`
Expected: PASS

### Task 2: Build the deterministic launch package generator

**Files:**
- Create: `business/revenue_launch.py`
- Modify: `business/fallbacks.py`
- Modify: `business/offer/agent.py`

- [ ] **Step 1: Write the failing test**

```python
def test_build_revenue_launch_package_defaults_to_invoiceops_guard():
    from business.revenue_launch import build_revenue_launch_package
    from core.state import BeaSession

    session = BeaSession(
        session_id="launch-test",
        user_input="Reduce SaaS billing mistakes before churn",
    )
    session.mission_summary = "Reduce SaaS billing mistakes before churn"
    session.metadata["company_name"] = "Demo SaaS"

    bundle = build_revenue_launch_package(session)

    assert bundle["product_name"] == "InvoiceOps Guard"
    assert bundle["cta"] == "Book a revenue leak audit"
    assert "landing/index.html" in bundle["files"]
    assert "outreach.md" in bundle["files"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_business_revenue_launch.py::test_build_revenue_launch_package_defaults_to_invoiceops_guard -q`
Expected: fail because the launch bundle is absent

- [ ] **Step 3: Implement the deterministic generator**

Create `build_revenue_launch_package(session)` with:
- product name
- pricing
- landing hero
- outreach opener
- qualification checklist
- first 10 target accounts or account filters

Use `InvoiceOps Guard` as the default package when the session context points to SaaS B2B revenue leaks.

- [ ] **Step 4: Hook `OfferDesignerAgent` to the launch bundle**

After parsing the offer report, store `session.metadata["launch_bundle"]` and call `core.business_actions.get_business_executor().execute("revenue.launch_package", ...)`.

- [ ] **Step 5: Run the test and verify it passes**

Run: `python -m pytest tests/test_business_revenue_launch.py -q`
Expected: PASS

### Task 3: Add launch-flow verification and regression coverage

**Files:**
- Modify: `tests/test_bea_autonomous_execution.py`
- Create: `tests/test_business_launch_flow.py`

- [ ] **Step 1: Write the failing test**

```python
def test_full_launch_flow_produces_invoiceops_guard_bundle(monkeypatch):
    from business.offer.agent import OfferDesignerAgent
    from config.settings import Settings
    from core.state import BeaSession

    calls = []

    class FakeExecutor:
        def execute(self, action_id, agent_output, mission_id="", project_name=""):
            calls.append((action_id, project_name))
            return {
                "ok": True,
                "files_created": [
                    "README.md",
                    "landing/index.html",
                    "outreach.md",
                    "qualification.md",
                ],
            }

    async def empty_response(*args, **kwargs):
        return type("R", (), {"content": ""})()

    monkeypatch.setattr("core.business_actions.get_business_executor", lambda: FakeExecutor())
    monkeypatch.setattr("core.llm_factory.LLMFactory.safe_invoke", empty_response)

    session = BeaSession(
        session_id="launch-flow-test",
        user_input="Reduce SaaS billing mistakes",
    )
    session.mission_summary = "Reduce SaaS billing mistakes"
    session.metadata["company_name"] = "Demo SaaS"

    agent = OfferDesignerAgent(Settings())
    import asyncio
    out = asyncio.run(agent.run(session))

    assert out.strip()
    assert session.metadata["launch_bundle"]["product_name"] == "InvoiceOps Guard"
    assert calls and calls[0][0] == "revenue.launch_package"
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `python -m pytest tests/test_business_launch_flow.py -q`
Expected: fail until the launch bundle is wired end-to-end

- [ ] **Step 3: Implement the flow verification**

Add assertions to the autonomous-execution regression file so empty LLM output still results in a complete launch bundle and not a silent success.

- [ ] **Step 4: Run the targeted suite**

Run: `python -m pytest tests/test_bea_autonomous_execution.py tests/test_business_revenue_launch.py tests/test_business_launch_flow.py -q`
Expected: all green

### Task 4: Validate the business bundle end to end

**Files:**
- No code changes expected unless validation exposes a real defect.

- [ ] **Step 1: Run lint and the targeted tests**

Run: `python -m ruff check --no-cache core/business_actions.py business/fallbacks.py business/offer/agent.py tests/test_bea_autonomous_execution.py tests/test_business_revenue_launch.py tests/test_business_launch_flow.py`

Run: `python -m pytest tests/test_bea_autonomous_execution.py tests/test_business_revenue_launch.py tests/test_business_launch_flow.py -q`

- [ ] **Step 2: Generate one real launch bundle locally**

Run the business executor on `revenue.launch_package` with the `InvoiceOps Guard` payload and verify the workspace contains a coherent sales bundle ready for manual outreach.

- [ ] **Step 3: Confirm first-euro readiness**

Check that the bundle includes:
- one clear offer
- one landing page
- one outreach sequence
- one qualification checklist
- one first-call script

If any piece is missing, fix the generator before considering the business ready.
