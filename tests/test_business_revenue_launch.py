from __future__ import annotations

from pathlib import Path


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


def test_revenue_launch_package_creates_sales_bundle(monkeypatch):
    from business.revenue_launch import build_revenue_launch_package
    from core import business_actions as ba
    from core.state import BeaSession

    written = {}

    def fake_write(self, path, content):
        written[str(path)] = content

    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    monkeypatch.setattr(ba.BusinessActionExecutor, "_write", fake_write)

    session = BeaSession(
        session_id="launch-package-test",
        user_input="Reduce SaaS billing mistakes before churn",
    )
    session.mission_summary = "Reduce SaaS billing mistakes before churn"
    session.metadata["company_name"] = "Demo SaaS"

    bundle = build_revenue_launch_package(session)
    executor = ba.BusinessActionExecutor()
    result = executor.execute(
        "revenue.launch_package",
        bundle,
        mission_id="m1",
        project_name=bundle["product_name"],
    )

    assert result["ok"] is True
    assert any(path.endswith("README.md") for path in written)
    assert any("landing" in path and "index.html" in path for path in written)
    assert any(path.endswith("outreach.md") for path in written)
    assert any(path.endswith("qualification.md") for path in written)
