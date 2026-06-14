"""Regression tests for Bea's autonomous file-producing execution path."""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace


def _output(content: str = "real output", success: bool = True):
    return SimpleNamespace(content=content, success=success, error="")


def test_file_producing_session_fails_without_materialized_actions():
    from core.orchestration.execution_supervisor import _check_session_outcome

    session = SimpleNamespace(
        error=None,
        agents_plan=[{"agent": "forge-builder"}],
        outputs={"forge-builder": _output()},
        final_report="Files are ready.",
        needs_actions=True,
        actions_executed=[],
        actions_pending=[],
        _raw_actions=[],
    )

    ok, reason, error_class = _check_session_outcome(session)

    assert ok is False
    assert error_class == "actions_not_materialized"
    assert "no file action" in reason


def test_file_producing_session_succeeds_after_action_execution():
    from core.orchestration.execution_supervisor import _check_session_outcome

    session = SimpleNamespace(
        error=None,
        agents_plan=[{"agent": "forge-builder"}],
        outputs={"forge-builder": _output()},
        final_report="Files are ready.",
        needs_actions=True,
        actions_executed=[{"target": "workspace/business/demo/README.md"}],
        actions_pending=[],
        _raw_actions=[],
    )

    ok, reason, error_class = _check_session_outcome(session)

    assert ok is True
    assert reason == ""
    assert error_class == ""


def test_materialized_actions_override_low_optional_agent_success_rate():
    from core.orchestration.execution_supervisor import _check_session_outcome

    session = SimpleNamespace(
        error=None,
        agents_plan=[{"agent": f"agent-{idx}"} for idx in range(7)],
        outputs={"agent-0": _output()},
        final_report="All requested files were created.",
        needs_actions=True,
        actions_executed=[
            {"target": "workspace/business/demo/README.md"},
            {"target": "workspace/business/demo/offer.md"},
        ],
        actions_pending=[],
        _raw_actions=[
            {"target": "workspace/business/demo/README.md"},
            {"target": "workspace/business/demo/offer.md"},
        ],
    )

    ok, reason, error_class = _check_session_outcome(session)

    assert ok is True
    assert reason == ""
    assert error_class == ""


def test_execution_mixin_preserves_cognition_outcome_object():
    from core.orchestration import execution_supervised_runner

    # After orchestrator split, the call lives in execution_supervised_runner
    source = inspect.getsource(execution_supervised_runner)

    assert "execute_mission_with_delegate_cognition" in source
    assert "return str(result)" not in source


def test_forge_builder_prompt_requires_executable_file_blocks():
    from agents.crew import ForgeBuilder

    builder = ForgeBuilder.__new__(ForgeBuilder)
    prompt = builder.system_prompt()

    assert "### Fichier:" in prompt
    assert "actions create_file" in prompt
    assert "pas accès" in prompt
    assert "16 000 caractères" in prompt


def test_forge_builder_receives_full_business_context():
    from agents.crew import ForgeBuilder
    from core.state import BeaSession, TaskMode

    session = BeaSession(
        session_id="business-context-test",
        user_input="Build the final business deliverables",
    )
    session.task_mode = TaskMode.BUSINESS
    session.mission_summary = "Build the final business deliverables"
    session.agents_plan = [{"agent": "forge-builder", "task": "Create final files"}]
    session.outputs = {
        "venture-builder": _output("V" * 1400),
        "offer-designer": _output("O" * 1400),
    }

    builder = ForgeBuilder.__new__(ForgeBuilder)
    message = builder.user_message(session)

    assert message.count("V") >= 1200
    assert message.count("O") >= 1200


def test_forge_file_blocks_are_deterministically_extracted():
    from agents.crew import extract_file_actions

    output = """### Fichier: workspace/business/demo/README.md
# Demo

### Fichier: workspace/business/demo/index.html
<h1>Demo</h1>
"""

    actions = extract_file_actions(output)

    assert [action["target"] for action in actions] == [
        "workspace/business/demo/README.md",
        "workspace/business/demo/index.html",
    ]
    assert all(action["action_type"] == "create_file" for action in actions)


def test_executor_does_not_duplicate_workspace_prefix():
    from executor.runner import WORKSPACE, _workspace_path

    target, error = _workspace_path("workspace/business/demo/README.md")

    assert error is None
    assert target == WORKSPACE.resolve() / "business/demo/README.md"


def test_risk_engine_detects_local_workspace():
    from core.state import RiskLevel
    from risk.engine import RiskEngine

    report = RiskEngine().analyze(
        action_type="create_file",
        target="workspace/business/demo/README.md",
    )

    assert report.level == RiskLevel.LOW
    assert report.requires_validation is False


def test_builder_failure_falls_back_to_ollama(monkeypatch):
    from config.settings import Settings
    from core.llm_factory import LLMFactory

    class FailingLLM:
        _bea_provider = "codex_direct"
        model = "primary"

        async def ainvoke(self, messages):
            raise RuntimeError("primary stream interrupted")

    class LocalLLM:
        _bea_provider = "ollama"
        model = "local"

        async def ainvoke(self, messages):
            return SimpleNamespace(content="local fallback output")

    factory = LLMFactory(Settings())
    monkeypatch.setattr(factory, "get", lambda role: FailingLLM())
    monkeypatch.setattr(
        factory,
        "_build_chain",
        lambda role, preferred: ["codex_direct", "ollama"],
    )
    monkeypatch.setattr(
        factory,
        "_build",
        lambda provider, role: LocalLLM() if provider == "ollama" else None,
    )

    response = asyncio.run(factory.safe_invoke([], role="builder", timeout=1.0))

    assert response.content == "local fallback output"


def test_empty_primary_response_falls_back_to_ollama(monkeypatch):
    from config.settings import Settings
    from core.llm_factory import LLMFactory

    class EmptyLLM:
        _bea_provider = "openrouter"
        model = "primary"

        async def ainvoke(self, messages):
            return SimpleNamespace(content="")

    class LocalLLM:
        _bea_provider = "ollama"
        model = "local"

        async def ainvoke(self, messages):
            return SimpleNamespace(content="local analysis")

    factory = LLMFactory(Settings())
    monkeypatch.setattr(factory, "get", lambda role: EmptyLLM())
    monkeypatch.setattr(factory, "_build_chain", lambda role, preferred: ["openrouter", "ollama"])
    monkeypatch.setattr(
        factory,
        "_build",
        lambda provider, role: LocalLLM() if provider == "ollama" else None,
    )

    response = asyncio.run(factory.safe_invoke([], role="analyst", timeout=1.0))

    assert response.content == "local analysis"


def test_business_agents_build_deterministic_fallbacks(monkeypatch):
    from config.settings import Settings
    from core.llm_factory import LLMFactory
    from core.state import BeaSession
    from business.offer.agent import OfferDesignerAgent
    from business.saas.agent import SaasBuilderAgent
    from business.trade_ops.agent import TradeOpsAgent
    from business.venture.agent import VentureBuilderAgent
    from business.workflow.agent import WorkflowArchitectAgent

    async def empty_response(*args, **kwargs):
        return SimpleNamespace(content="")

    monkeypatch.setattr(LLMFactory, "safe_invoke", empty_response)

    session = BeaSession(
        session_id="fallback-business-test",
        user_input="Créer une offre pour réduire les relances clients",
    )
    session.mission_summary = "Créer une offre pour réduire les relances clients"
    session.metadata["company_name"] = "Acme SARL"
    session.metadata["trade_sector"] = "relances clients"

    agents = [
        VentureBuilderAgent(Settings()),
        OfferDesignerAgent(Settings()),
        WorkflowArchitectAgent(Settings()),
        SaasBuilderAgent(Settings()),
        TradeOpsAgent(Settings()),
    ]

    for agent in agents:
        out = asyncio.run(agent.run(session))
        assert out.strip(), f"{agent.name} should produce a deterministic fallback"
        assert session.get_output(agent.name).strip(), f"{agent.name} output must be stored as success"
        if agent.name == "offer-designer":
            assert session.metadata["launch_bundle"]["product_name"] == "InvoiceOps Guard"
            assert "landing/index.html" in session.metadata["launch_bundle"]["files"]


def test_cognition_accepts_string_complexity():
    source = inspect.getsource(
        __import__(
            "core.cognition.orchestrator",
            fromlist=["CognitionOrchestrator"],
        ).CognitionOrchestrator.execute_mission_with_delegate_cognition
    )

    assert '"complex": 8' in source


def test_materialized_actions_use_deterministic_report():
    from core.bea_executor import BeaOrchestrator

    source = inspect.getsource(BeaOrchestrator._generate_report)

    assert "Mission matérialisée avec" in source
    assert "if session.actions_executed:" in source


def test_session_status_uses_materialized_actions_as_success():
    from core.bea_executor import BeaOrchestrator

    session = SimpleNamespace(
        agents_plan=[{"agent": f"agent-{idx}"} for idx in range(7)],
        outputs={"agent-0": _output()},
        error=None,
        needs_actions=True,
        actions_executed=[{"target": "workspace/business/demo/README.md"}],
        actions_pending=[],
        _raw_actions=[{"target": "workspace/business/demo/README.md"}],
    )

    status = BeaOrchestrator.__new__(BeaOrchestrator)._compute_session_status(session)

    assert status["label"] == "SUCCESS"
    assert status["rate"] == 1.0
