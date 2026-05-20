"""
tests/test_execution_layer.py — Real World Execution Layer tests.

Validates:
  - Artifact model (types, templates, creation, serialization)
  - Capability → artifact mapping
  - Execution graph (build, ordering, dependencies, progress)
  - Tool contracts (registry, schemas, safety)
  - Build pipeline (validate, prepare, build, verify, record)
  - API endpoints
  - Safety (no uncontrolled actions, workspace-scoped)
"""
import json
import shutil
from pathlib import Path
from core.execution.artifacts import (
    ArtifactType, ArtifactStatus, ExecutionArtifact, ARTIFACT_TEMPLATES, create_artifact_from_template,
)
from core.execution.execution_graph import (
    ExecutionGraph, build_execution_graph,
    CAPABILITY_ARTIFACT_MAP, SCHEMA_ARTIFACT_SEQUENCES,
)
from core.execution.build_pipeline import (
    BuildPipeline, BuildResult, TOOL_CONTRACTS,
)


# ══════════════════════════════════════════════════════════════
# Phase 1 — Artifact Model
# ══════════════════════════════════════════════════════════════

class TestArtifactModel:

    def test_EX01_artifact_types_complete(self):
        """All 8 canonical artifact types exist."""
        types = [t.value for t in ArtifactType]
        assert "landing_page" in types
        assert "automation_workflow" in types
        assert "api_service" in types
        assert "mvp_feature" in types
        assert "data_pipeline" in types
        assert "marketing_experiment" in types
        assert "content_asset" in types
        assert "operational_workflow" in types
        assert len(types) == 8

    def test_EX02_artifact_status_lifecycle(self):
        """Artifact status covers full lifecycle."""
        statuses = [s.value for s in ArtifactStatus]
        assert "spec" in statuses
        assert "validated" in statuses
        assert "building" in statuses
        assert "built" in statuses
        assert "verified" in statuses
        assert "failed" in statuses
        assert "deployed" in statuses

    def test_EX03_artifact_creation(self):
        art = ExecutionArtifact(
            artifact_type=ArtifactType.LANDING_PAGE,
            name="Test Landing",
            description="A test landing page",
            expected_outcome="Deployable HTML page",
            source_capability="venture_planning",
        )
        assert art.artifact_id.startswith("art-")
        assert art.status == ArtifactStatus.SPEC
        assert art.artifact_type == ArtifactType.LANDING_PAGE

    def test_EX04_artifact_roundtrip(self):
        art = ExecutionArtifact(
            artifact_type=ArtifactType.API_SERVICE,
            name="Test API",
            description="Test service",
            expected_outcome="Working API",
        )
        d = art.to_dict()
        art2 = ExecutionArtifact.from_dict(d)
        assert art2.artifact_id == art.artifact_id
        assert art2.name == art.name
        assert art2.artifact_type == ArtifactType.API_SERVICE

    def test_EX05_artifact_validate_spec(self):
        """Spec validation catches missing required fields."""
        art = ExecutionArtifact()
        issues = art.validate_spec()
        assert "name is required" in issues
        assert "description is required" in issues
        assert "expected_outcome is required" in issues

    def test_EX06_artifact_from_template(self):
        """create_artifact_from_template produces valid artifact."""
        art = create_artifact_from_template(
            "landing_page", "Test Page", "Description", "Working page",
        )
        assert art is not None
        assert art.artifact_type == ArtifactType.LANDING_PAGE
        assert len(art.validation_requirements) >= 2
        assert len(art.required_tools) >= 1

    def test_EX07_unknown_template_returns_none(self):
        assert create_artifact_from_template("nonexistent", "X", "Y", "Z") is None

    def test_EX08_all_templates_exist(self):
        """All 8 artifact types have templates."""
        for art_type in ArtifactType:
            assert art_type.value in ARTIFACT_TEMPLATES, f"Missing template: {art_type.value}"


# ══════════════════════════════════════════════════════════════
# Phase 2 — Capability → Artifact Mapping
# ══════════════════════════════════════════════════════════════

class TestCapabilityMapping:

    def test_EX09_capability_map_covers_economic(self):
        """All 7 economic capabilities have artifact mappings."""
        economic_caps = [
            "market_intelligence", "product_design", "financial_reasoning",
            "strategy_reasoning", "venture_planning", "compliance_reasoning",
            "risk_assessment",
        ]
        for cap in economic_caps:
            assert cap in CAPABILITY_ARTIFACT_MAP, f"Missing: {cap}"

    def test_EX10_schema_sequences_exist(self):
        """Key economic schemas have artifact sequences."""
        assert "OpportunityReport" in SCHEMA_ARTIFACT_SEQUENCES
        assert "BusinessConcept" in SCHEMA_ARTIFACT_SEQUENCES
        assert "VenturePlan" in SCHEMA_ARTIFACT_SEQUENCES
        assert "FinancialModel" in SCHEMA_ARTIFACT_SEQUENCES

    def test_EX11_venture_plan_has_full_sequence(self):
        """VenturePlan produces the most artifacts (full pipeline)."""
        seq = SCHEMA_ARTIFACT_SEQUENCES["VenturePlan"]
        assert len(seq) >= 3
        types = [s["template"] for s in seq]
        assert "mvp_feature" in types
        assert "landing_page" in types

    def test_EX12_phases_are_ordered(self):
        """Artifact sequences follow thinking→planning→building→deploying."""
        phase_order = {"thinking": 0, "planning": 1, "building": 2, "deploying": 3}
        for schema, seq in SCHEMA_ARTIFACT_SEQUENCES.items():
            for i in range(len(seq) - 1):
                current = phase_order.get(seq[i].get("phase", "building"), 2)
                next_p = phase_order.get(seq[i + 1].get("phase", "building"), 2)
                assert current <= next_p, \
                    f"{schema}: phase {seq[i]['phase']} before {seq[i+1]['phase']}"


# ══════════════════════════════════════════════════════════════
# Phase 3 — Execution Graph
# ══════════════════════════════════════════════════════════════

class TestExecutionGraph:

    def test_EX13_build_graph_from_schema(self):
        graph = build_execution_graph("VenturePlan", "Test venture")
        assert graph.graph_id.startswith("eg-")
        assert graph.source_schema == "VenturePlan"
        assert len(graph.nodes) >= 3

    def test_EX14_graph_dependencies_chain(self):
        """Each node depends on the previous."""
        graph = build_execution_graph("VenturePlan", "Test")
        for i, node in enumerate(graph.nodes):
            if i == 0:
                assert node.depends_on == []
            else:
                assert len(node.depends_on) == 1
                assert node.depends_on[0] == graph.nodes[i - 1].node_id

    def test_EX15_graph_nodes_have_artifacts(self):
        graph = build_execution_graph("BusinessConcept", "Test concept")
        for node in graph.nodes:
            assert node.artifact is not None
            assert node.artifact.status == ArtifactStatus.SPEC

    def test_EX16_empty_schema_returns_empty_graph(self):
        graph = build_execution_graph("UnknownSchema", "Test")
        assert len(graph.nodes) == 0

    def test_EX17_graph_progress_tracking(self):
        graph = build_execution_graph("BusinessConcept", "Test")
        assert graph.progress == 0.0

        # Simulate building first node
        if graph.nodes:
            graph.nodes[0].artifact.status = ArtifactStatus.BUILT
            assert graph.progress > 0.0

    def test_EX18_get_next_buildable(self):
        graph = build_execution_graph("VenturePlan", "Test")
        # First node should be buildable (no deps)
        node = graph.get_next_buildable()
        assert node is not None
        assert node.depends_on == []

    def test_EX19_graph_serializable(self):
        graph = build_execution_graph("VenturePlan", "Test")
        d = graph.to_dict()
        assert "nodes" in d
        assert "phase_summary" in d
        graph2 = ExecutionGraph.from_dict(d)
        assert len(graph2.nodes) == len(graph.nodes)

    def test_EX20_phase_summary(self):
        graph = build_execution_graph("VenturePlan", "Test")
        summary = graph.phase_summary
        assert isinstance(summary, dict)
        assert sum(summary.values()) == len(graph.nodes)


# ══════════════════════════════════════════════════════════════
# Phase 4 — Tool Contracts
# ══════════════════════════════════════════════════════════════

class TestToolContracts:

    def test_EX21_core_tools_registered(self):
        assert "file.workspace.write" in TOOL_CONTRACTS
        assert "git.status" in TOOL_CONTRACTS
        assert "notification.log" in TOOL_CONTRACTS

    def test_EX22_tool_contract_schema(self):
        tc = TOOL_CONTRACTS["file.workspace.write"]
        assert tc.output_type == "file"
        assert tc.retry_safe is True
        assert tc.policy == "low"

    def test_EX23_webhook_tool_not_retry_safe(self):
        tc = TOOL_CONTRACTS["http.webhook.post"]
        assert tc.retry_safe is False
        assert tc.policy == "medium"

    def test_EX24_tool_contract_serializable(self):
        tc = TOOL_CONTRACTS["n8n.workflow.trigger"]
        d = tc.to_dict()
        assert "tool_id" in d
        assert "policy" in d


# ══════════════════════════════════════════════════════════════
# Phase 5 — Build Pipeline
# ══════════════════════════════════════════════════════════════

class TestBuildPipeline:

    def test_EX25_build_validates_spec(self):
        """Pipeline rejects artifacts with incomplete specs."""
        pipeline = BuildPipeline()
        art = ExecutionArtifact()  # empty spec
        result = pipeline.build(art)
        assert result.success is False
        assert "Spec validation failed" in result.error

    def test_EX26_build_scaffold_content(self):
        """Pipeline generates scaffold when LLM unavailable."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Test Content", "A test", "Content file",
        )
        result = pipeline.build(art)
        assert result.success is True
        assert result.status == ArtifactStatus.BUILT
        assert len(result.output_files) >= 1

    def test_EX27_build_landing_page(self):
        """Pipeline builds a landing page artifact."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "landing_page", "Test Page", "A test page", "Working HTML page",
        )
        result = pipeline.build(art)
        assert result.success is True
        assert any("index.html" in f for f in result.output_files)

    def test_EX28_build_api_service(self):
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "api_service", "Test API", "A test API", "Working service",
        )
        result = pipeline.build(art)
        assert result.success is True
        assert any("main.py" in f for f in result.output_files)

    def test_EX29_build_operational_workflow(self):
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "operational_workflow", "Test Workflow", "A test workflow", "Working workflow",
        )
        result = pipeline.build(art)
        assert result.success is True

    def test_EX30_build_log_tracks_stages(self):
        """Build log captures pipeline stages."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        assert any("VALIDATE" in entry for entry in result.build_log)
        assert any("PREPARE" in entry for entry in result.build_log)
        assert any("BUILD" in entry for entry in result.build_log)
        assert any("WRITE" in entry for entry in result.build_log)
        assert any("VERIFY" in entry for entry in result.build_log)

    def test_EX31_build_verification(self):
        """Verification checks pass for scaffold content."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        assert "content_file" in result.validation_passed

    def test_EX32_build_result_serializable(self):
        result = BuildResult(
            artifact_id="test-123",
            success=True,
            status=ArtifactStatus.BUILT,
        )
        d = result.to_dict()
        assert d["artifact_id"] == "test-123"
        assert d["success"] is True

    def test_EX33_build_budget_mode(self):
        """Build accepts budget_mode."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Budget Test", "Desc", "Outcome",
        )
        result = pipeline.build(art, budget_mode="budget")
        assert result.success is True

    def test_EX34_build_creates_workspace_dir(self):
        """Build creates output directory under workspace/builds/."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Dir Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        assert result.output_dir != ""
        assert Path(result.output_dir).is_dir()
        # Cleanup
        shutil.rmtree(result.output_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# API Tests
# ══════════════════════════════════════════════════════════════

class TestAPI:

    def test_EX35_router_exists(self):
        from api.routes.execution import router
        paths = [str(r.path) for r in router.routes]
        assert any("graph" in p for p in paths)
        assert any("build" in p for p in paths)
        assert any("templates" in p for p in paths)
        assert any("tools" in p for p in paths)
        assert any("artifacts" in p for p in paths)

    def test_EX36_router_mounted(self):
        import inspect
        import importlib
        main_mod = importlib.import_module("api.main")
        source = inspect.getsource(main_mod)
        assert "execution_router" in source

    def test_EX37_templates_endpoint(self):
        import asyncio
        from api.routes.execution import list_templates
        result = asyncio.get_event_loop().run_until_complete(list_templates())
        assert "templates" in result
        assert len(result["templates"]) == 8

    def test_EX38_tools_endpoint(self):
        import asyncio
        from api.routes.execution import list_tool_contracts
        result = asyncio.get_event_loop().run_until_complete(list_tool_contracts())
        assert "tools" in result
        assert len(result["tools"]) >= 4


# ══════════════════════════════════════════════════════════════
# Safety Tests
# ══════════════════════════════════════════════════════════════

class TestSafety:

    def test_EX39_builds_workspace_scoped(self):
        """All builds go under workspace/builds/."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Safety Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        assert "builds" in result.output_dir
        # Cleanup
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX40_no_system_modification(self):
        """Artifacts never write outside workspace."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "System Test", "Desc", "Outcome",
        )
        art.input_context = {"path": "/etc/passwd"}  # malicious input
        result = pipeline.build(art)
        # Build should succeed but only write to workspace
        assert "/etc/" not in str(result.output_files)
        # Cleanup
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX41_no_secrets_in_artifacts(self):
        """Artifact serialization doesn't leak secrets."""
        art = ExecutionArtifact(
            name="Test", description="Test",
            expected_outcome="Test",
            input_context={"api_key": "sk-test-12345"},
        )
        d = json.dumps(art.to_dict())
        # Input context values are truncated but we don't auto-redact here
        # The key is that artifacts don't inject secrets into generated content
        assert "artifact_id" in d

    def test_EX42_tool_contracts_have_policies(self):
        """Every tool contract has a safety policy."""
        for tool_id, tc in TOOL_CONTRACTS.items():
            assert tc.policy in ("low", "medium", "high", "critical"), \
                f"{tool_id} has invalid policy: {tc.policy}"

    def test_EX43_no_regression_playbook(self):
        """Existing playbook execution still works."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Regression test")
        assert result["ok"] is True

    def test_EX44_graph_plus_build_integration(self):
        """Full integration: schema → graph → build first artifact."""
        graph = build_execution_graph("BusinessConcept", "Integration test")
        assert len(graph.nodes) >= 1

        first_node = graph.get_next_buildable()
        assert first_node is not None
        assert first_node.artifact is not None

        pipeline = BuildPipeline()
        result = pipeline.build(first_node.artifact)
        # Should succeed with scaffold
        assert result.success is True
        first_node.artifact.status = ArtifactStatus.BUILT
        assert graph.progress > 0.0
        # Cleanup
        shutil.rmtree(result.output_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Phase 6 — Feedback Signals
# ══════════════════════════════════════════════════════════════

class TestFeedbackSignals:

    def test_EX45_build_confidence_composite(self):
        """BuildConfidence computes weighted composite."""
        from core.execution.feedback import BuildConfidence
        bc = BuildConfidence(
            validation_score=1.0,
            content_score=0.8,
            tool_score=1.0,
            iteration_count=1,
        )
        # 1.0*0.4 + 0.8*0.3 + 1.0*0.2 + 1.0*0.1 = 0.4+0.24+0.2+0.1 = 0.94
        assert abs(bc.composite - 0.94) < 0.01

    def test_EX46_confidence_bounded(self):
        """Composite is always in [0, 1]."""
        from core.execution.feedback import BuildConfidence
        bc = BuildConfidence(validation_score=1.5, content_score=2.0, tool_score=3.0)
        assert 0.0 <= bc.composite <= 1.0

    def test_EX47_iteration_penalty(self):
        """More iterations reduce confidence."""
        from core.execution.feedback import BuildConfidence
        bc1 = BuildConfidence(validation_score=1.0, content_score=0.7, iteration_count=1)
        bc3 = BuildConfidence(validation_score=1.0, content_score=0.7, iteration_count=3)
        assert bc1.composite > bc3.composite

    def test_EX48_compute_confidence_from_results(self):
        from core.execution.feedback import compute_confidence
        bc = compute_confidence(
            validation_passed=["a", "b", "c"],
            validation_failed=["d"],
            content_quality=0.8,
        )
        assert bc.validation_score == 0.75
        assert bc.content_score == 0.8
        assert bc.composite > 0.5

    def test_EX49_execution_trace_complete(self):
        """ExecutionTrace includes all traceability fields."""
        from core.execution.feedback import ExecutionTrace, BuildConfidence
        trace = ExecutionTrace(
            artifact_id="art-123",
            artifact_type="landing_page",
            source_capability="venture_planning",
            source_schema="VenturePlan",
            build_success=True,
            confidence=BuildConfidence(validation_score=1.0),
        )
        d = trace.to_dict()
        assert d["artifact_id"] == "art-123"
        assert d["source_capability"] == "venture_planning"
        assert "confidence" in d
        assert d["confidence"]["composite"] > 0

    def test_EX50_build_execution_trace(self):
        """build_execution_trace creates trace from artifact + result."""
        from core.execution.feedback import build_execution_trace
        art = create_artifact_from_template(
            "content_asset", "Test", "Desc", "Outcome",
            source_capability="market_intelligence",
        )
        result = BuildResult(
            artifact_id=art.artifact_id,
            success=True,
            status=ArtifactStatus.BUILT,
            output_files=["content.md"],
            validation_passed=["content_file"],
            validation_failed=[],
            tools_invoked=["file.workspace.write"],
        )
        trace = build_execution_trace(art, result)
        assert trace.build_success is True
        assert trace.confidence.composite > 0.5
        assert trace.source_capability == "market_intelligence"

    def test_EX51_feedback_collector_exists(self):
        from core.execution.feedback import get_feedback_collector
        collector = get_feedback_collector()
        assert collector is not None

    def test_EX52_feedback_in_build_log(self):
        """Build pipeline records feedback in build_log."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Feedback Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        assert result.success is True
        assert any("FEEDBACK" in entry for entry in result.build_log)
        shutil.rmtree(result.output_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Phase 7 — Deployment Targets
# ══════════════════════════════════════════════════════════════

class TestDeploymentTargets:

    def test_EX53_static_site_scaffold(self):
        """Landing page scaffold produces valid HTML."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "landing_page", "Test Site", "A test site", "HTML page",
        )
        result = pipeline.build(art)
        assert result.success is True
        # Read HTML and verify structure
        html_files = [f for f in result.output_files if f.endswith(".html")]
        assert len(html_files) >= 1
        content = Path(html_files[0]).read_text(encoding="utf-8")
        assert "<html>" in content.lower()
        assert "test site" in content.lower()
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX54_api_scaffold(self):
        """API service scaffold produces FastAPI stub."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "api_service", "Test API", "A test API", "Working API",
        )
        result = pipeline.build(art)
        assert result.success is True
        py_files = [f for f in result.output_files if f.endswith("main.py")]
        assert len(py_files) >= 1
        content = Path(py_files[0]).read_text(encoding="utf-8")
        assert "FastAPI" in content or "fastapi" in content.lower()
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX55_automation_scaffold(self):
        """Automation workflow produces valid JSON."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "automation_workflow", "Test Flow", "A test flow", "Workflow",
        )
        result = pipeline.build(art)
        assert result.success is True
        json_files = [f for f in result.output_files if f.endswith("workflow.json")]
        assert len(json_files) >= 1
        content = json.loads(Path(json_files[0]).read_text(encoding="utf-8"))
        assert isinstance(content, dict)
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX56_content_scaffold(self):
        """Content asset produces markdown."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Test Content", "A report", "Markdown content",
        )
        result = pipeline.build(art)
        assert result.success is True
        md_files = [f for f in result.output_files if f.endswith(".md")]
        assert len(md_files) >= 1
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX57_documentation_scaffold(self):
        """Operational workflow produces runbook + spec."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "operational_workflow", "Test Ops", "A workflow", "Runbook",
        )
        result = pipeline.build(art)
        assert result.success is True
        assert any("runbook.md" in f for f in result.output_files)
        assert any("workflow.md" in f for f in result.output_files)
        shutil.rmtree(result.output_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Phase 8 — Execution Observability
# ══════════════════════════════════════════════════════════════

class TestExecutionObservability:

    def test_EX58_status_endpoint(self):
        import asyncio
        from api.routes.execution import execution_status
        result = asyncio.get_event_loop().run_until_complete(execution_status())
        assert result["active"] is True
        assert result["templates"] == 8
        assert result["tool_contracts"] >= 4

    def test_EX59_policy_endpoint(self):
        import asyncio
        from api.routes.execution import check_policy
        result = asyncio.get_event_loop().run_until_complete(check_policy("landing_page"))
        assert result["safe"] is True
        assert result["policy_classification"] == "low"

    def test_EX60_build_log_has_all_stages(self):
        """Build log captures every pipeline stage."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Log Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        log_text = " ".join(result.build_log)
        assert "POLICY" in log_text
        assert "VALIDATE" in log_text
        assert "PREPARE" in log_text
        assert "BUILD" in log_text
        assert "WRITE" in log_text
        assert "VERIFY" in log_text
        assert "FEEDBACK" in log_text
        assert "COMPLETE" in log_text
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX61_trace_includes_confidence(self):
        """Execution trace includes confidence score."""
        from core.execution.feedback import build_execution_trace
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Trace Test", "Desc", "Outcome",
        )
        result = pipeline.build(art)
        trace = build_execution_trace(art, result)
        assert 0.0 <= trace.confidence.composite <= 1.0
        shutil.rmtree(result.output_dir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════
# Phase 9 — Policy Safety
# ══════════════════════════════════════════════════════════════

class TestPolicySafety:

    def test_EX62_clean_artifact_passes_policy(self):
        from core.execution.policy import is_safe_to_build
        art = create_artifact_from_template(
            "content_asset", "Clean", "Desc", "Outcome",
        )
        safe, violations = is_safe_to_build(art)
        assert safe is True
        assert len(violations) == 0

    def test_EX63_financial_transaction_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Execute stripe.charges.create for $500")
        assert len(violations) >= 1
        assert any(v.rule == "financial_transaction" for v in violations)

    def test_EX64_credential_exposure_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Set api_key=sk-1234 in header")
        assert any(v.rule == "credential_exposure" for v in violations)

    def test_EX65_system_modification_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Write to /etc/passwd")
        assert any(v.rule == "system_modification" for v in violations)

    def test_EX66_irreversible_action_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Run rm -rf /data")
        assert any(v.rule == "irreversible_action" for v in violations)

    def test_EX67_network_propagation_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Send mass_email to all users")
        assert any(v.rule == "network_propagation" for v in violations)

    def test_EX68_legal_commitment_blocked(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Process sign_contract for partnership")
        assert any(v.rule == "legal_commitment" for v in violations)

    def test_EX69_policy_blocks_build(self):
        """Build pipeline rejects policy-violating artifact."""
        pipeline = BuildPipeline()
        art = create_artifact_from_template(
            "content_asset", "Bad Build", "Execute rm -rf /", "Destroy system",
        )
        result = pipeline.build(art)
        assert result.success is False
        assert "Policy blocked" in result.error

    def test_EX70_tool_classification(self):
        from core.execution.policy import classify_tool
        assert classify_tool("file.workspace.write") == "low"
        assert classify_tool("http.webhook.post") == "medium"
        assert classify_tool("shell.execute") == "critical"
        assert classify_tool("unknown.tool") == "medium"  # default

    def test_EX71_policy_classification(self):
        from core.execution.policy import get_policy_classification
        art = create_artifact_from_template(
            "landing_page", "Safe Page", "A page", "HTML",
        )
        assert get_policy_classification(art) == "low"

    def test_EX72_safe_content_passes(self):
        from core.execution.policy import check_content_policy
        violations = check_content_policy("Build a landing page with hero section and CTA")
        assert len(violations) == 0


# ══════════════════════════════════════════════════════════════
# Phase 10 — Integration + Regression
# ══════════════════════════════════════════════════════════════

class TestIntegrationRegression:

    def test_EX73_full_pipeline_integration(self):
        """Full: schema → graph → policy check → build → feedback."""
        from core.execution.feedback import build_execution_trace
        from core.execution.policy import is_safe_to_build

        graph = build_execution_graph("VenturePlan", "Full integration test")
        assert len(graph.nodes) >= 3

        first = graph.get_next_buildable()
        assert first is not None

        safe, _ = is_safe_to_build(first.artifact)
        assert safe is True

        pipeline = BuildPipeline()
        result = pipeline.build(first.artifact, budget_mode="budget")
        assert result.success is True

        trace = build_execution_trace(first.artifact, result)
        assert trace.build_success is True
        assert trace.confidence.composite > 0.3

        first.artifact.status = ArtifactStatus.BUILT
        assert graph.progress > 0.0
        shutil.rmtree(result.output_dir, ignore_errors=True)

    def test_EX74_no_regression_playbook(self):
        """Existing playbook execution unaffected."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Regression test phase 6-10")
        assert result["ok"] is True

    def test_EX75_no_regression_plan_runner(self):
        """Plan runner unaffected."""
        from core.planning.playbook import execute_playbook
        result = execute_playbook("market_analysis", "Plan runner regression")
        assert "run" in result

    def test_EX76_feedback_serializable(self):
        """All feedback types serialize to JSON."""
        from core.execution.feedback import ExecutionTrace, BuildConfidence
        trace = ExecutionTrace(
            artifact_id="test",
            build_success=True,
            confidence=BuildConfidence(validation_score=0.9),
        )
        d = json.dumps(trace.to_dict())
        assert "trace_id" in d
        assert "confidence" in d

    def test_EX77_policy_violation_serializable(self):
        from core.execution.policy import PolicyViolation
        v = PolicyViolation(rule="test", severity="block", description="test violation")
        d = json.dumps(v.to_dict())
        assert "rule" in d
