from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_full_launch_flow_produces_invoiceops_guard_bundle(monkeypatch):
    from business.offer.agent import OfferDesignerAgent
    from config.settings import Settings
    from core.llm_factory import LLMFactory
    from core.state import BeaSession
    from pathlib import Path
    from core import business_actions as ba

    written = {}

    def fake_write(self, path, content):
        written[str(path)] = content

    async def empty_response(*args, **kwargs):
        return SimpleNamespace(content="")

    monkeypatch.setattr(LLMFactory, "safe_invoke", empty_response)
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)
    monkeypatch.setattr(ba.BusinessActionExecutor, "_write", fake_write)

    session = BeaSession(
        session_id="launch-flow-test",
        user_input="Reduce SaaS billing mistakes",
    )
    session.mission_summary = "Reduce SaaS billing mistakes"
    session.metadata["company_name"] = "Demo SaaS"

    agent = OfferDesignerAgent(Settings())
    out = asyncio.run(agent.run(session))

    assert out.strip()
    assert session.metadata["launch_bundle"]["product_name"] == "InvoiceOps Guard"

    artifacts = session.metadata["launch_artifacts"]
    project_dir = Path(artifacts["project_dir"])
    assert project_dir
    assert artifacts["files_created"]
    assert any("landing" in item and "index.html" in item for item in artifacts["files_created"])
    assert "outreach.md" in artifacts["files_created"]
    assert "qualification.md" in artifacts["files_created"]
    assert any("landing" in path and "index.html" in path for path in written)
