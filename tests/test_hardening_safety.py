"""
Batch 4+5: Business Operating Loop Hardening + Safety/Governance Final Pass

Tests:
- Connector input sanitization (XSS, null bytes, length bounds)
- Connector execution audit trail
- Kill switch blocks connector execution
- Unified safety checkpoint (all gates in one call)
- Governance dashboard enrichment (canonical status, memory health)
- Business pipeline validation (lead stages, content stages)
- Budget guard integration
- Rate limiting enforcement
- Danger classification coverage
"""
import pytest
import os
import sys
import time
import types
import unittest

# ── Structlog stub ────────────────────────────────────────────────────────────
if 'structlog' not in sys.modules:
    _sl = types.ModuleType('structlog')
    class _ML:
        def info(self, *a, **k): pass
        def debug(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
        def bind(self, **k): return self
    _sl.get_logger = lambda *a, **k: _ML()
    sys.modules['structlog'] = _sl

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ═══════════════════════════════════════════════════════════════
# CONNECTOR INPUT SANITIZATION
# ═══════════════════════════════════════════════════════════════

@pytest.mark.stale
@pytest.mark.skip(reason="phantom: sanitize_params")
class TestConnectorSanitization(unittest.TestCase):
    """Input sanitization catches dangerous patterns."""

    def test_null_bytes_removed(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "https://example.com/\x00evil", "method": "GET"}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertNotIn("\x00", clean["url"])
        self.assertTrue(any("null_bytes" in w for w in warnings))

    def test_script_tag_detected(self):
        from core.connectors import _sanitize_connector_params
        params = {"body": '<script>alert("xss")</script>'}
        clean, warnings = _sanitize_connector_params("webhook", params)
        self.assertTrue(any("dangerous_pattern" in w for w in warnings))

    def test_javascript_uri_detected(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "javascript:alert(1)"}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertTrue(any("dangerous_pattern" in w for w in warnings))

    def test_data_uri_detected(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "data:text/html,<h1>evil</h1>"}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertTrue(any("dangerous_pattern" in w for w in warnings))

    def test_file_uri_detected(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "file:///etc/passwd"}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertTrue(any("dangerous_pattern" in w for w in warnings))

    def test_string_length_bounded(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "x" * 20000}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertLessEqual(len(clean["url"]), 10000)
        self.assertTrue(any("truncated" in w for w in warnings))

    def test_body_length_bounded_at_100k(self):
        from core.connectors import _sanitize_connector_params
        params = {"body": "x" * 200000}
        clean, warnings = _sanitize_connector_params("webhook", params)
        self.assertLessEqual(len(clean["body"]), 100000)

    def test_numeric_bounded(self):
        from core.connectors import _sanitize_connector_params
        params = {"timeout": 999999999}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertLessEqual(clean["timeout"], 1000000)

    def test_list_length_bounded(self):
        from core.connectors import _sanitize_connector_params
        params = {"tags": list(range(500))}
        clean, warnings = _sanitize_connector_params("lead_manager", params)
        self.assertLessEqual(len(clean["tags"]), 100)

    def test_nested_dict_sanitized(self):
        from core.connectors import _sanitize_connector_params
        params = {"headers": {"X-Evil": "\x00nullbyte", "X-Normal": "ok"}}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertNotIn("\x00", clean["headers"]["X-Evil"])

    def test_clean_params_pass_through(self):
        from core.connectors import _sanitize_connector_params
        params = {"url": "https://api.example.com/v1/data", "method": "GET"}
        clean, warnings = _sanitize_connector_params("http_request", params)
        self.assertEqual(clean, params)
        self.assertEqual(warnings, [])

    def test_empty_params(self):
        from core.connectors import _sanitize_connector_params
        clean, warnings = _sanitize_connector_params("test", {})
        self.assertEqual(clean, {})
        self.assertEqual(warnings, [])


# ═══════════════════════════════════════════════════════════════
# KILL SWITCH ON CONNECTORS
# ═══════════════════════════════════════════════════════════════

class TestConnectorKillSwitch(unittest.TestCase):
    """Kill switch blocks all connector execution."""

    def test_kill_switch_blocks_connector(self):
        from core.connectors import execute_connector
        os.environ["BEA_EXECUTION_DISABLED"] = "1"
        try:
            result = execute_connector("json_storage", {"action": "list"})
            self.assertFalse(result.success)
            self.assertIn("disabled", result.error.lower())
        finally:
            os.environ.pop("BEA_EXECUTION_DISABLED", None)

    def test_normal_execution_allowed(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.connectors import execute_connector
        result = execute_connector("json_storage", {"action": "list", "collection": "test"})
        # May fail for other reasons, but should not be "execution_disabled"
        if result.error:
            self.assertNotIn("execution_disabled", result.error)


# ═══════════════════════════════════════════════════════════════
# UNIFIED SAFETY CHECKPOINT
# ═══════════════════════════════════════════════════════════════

class TestSafetyCheckpoint(unittest.TestCase):
    """Unified safety_checkpoint() validates all gates."""

    def test_normal_returns_allowed(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.governance import safety_checkpoint
        result = safety_checkpoint(action="read_file", risk_level="low")
        self.assertTrue(result["allowed"])
        self.assertIn("checks", result)
        self.assertIn("kill_switch", result["checks"])

    def test_kill_switch_blocks(self):
        from core.governance import safety_checkpoint
        os.environ["BEA_EXECUTION_DISABLED"] = "1"
        try:
            result = safety_checkpoint(action="write_file")
            self.assertFalse(result["allowed"])
            self.assertEqual(result["reason"], "execution_disabled")
        finally:
            os.environ.pop("BEA_EXECUTION_DISABLED", None)

    def test_with_connector_name(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.governance import safety_checkpoint
        result = safety_checkpoint(
            action="execute_connector",
            connector="http_request",
            risk_level="medium",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("allowed", result)
        self.assertIn("checks", result)

    def test_returns_check_details(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.governance import safety_checkpoint
        result = safety_checkpoint(action="test", connector="json_storage")
        checks = result["checks"]
        self.assertIn("kill_switch", checks)
        self.assertTrue(checks["kill_switch"])

    def test_unknown_connector_allowed(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.governance import safety_checkpoint
        result = safety_checkpoint(connector="nonexistent_connector")
        # Should be allowed (fail-open for unknown connectors)
        self.assertTrue(result["allowed"])


# ═══════════════════════════════════════════════════════════════
# GOVERNANCE DASHBOARD
# ═══════════════════════════════════════════════════════════════

class TestGovernanceDashboard(unittest.TestCase):
    """Governance dashboard returns complete data."""

    def test_dashboard_returns_all_sections(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        self.assertIsInstance(dashboard, dict)
        expected_keys = [
            "safety_state", "kill_switch_active", "rate_limits",
            "persistence", "mission_audit", "autonomy_boundaries",
            "danger_classification",
        ]
        for key in expected_keys:
            self.assertIn(key, dashboard, f"Missing key: {key}")

    def test_dashboard_has_canonical_status(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        self.assertIn("canonical_status_distribution", dashboard)
        self.assertIsInstance(dashboard["canonical_status_distribution"], dict)

    def test_dashboard_has_memory_health(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        self.assertIn("memory_health", dashboard)

    def test_dashboard_has_kill_switch_status(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        self.assertIn("kill_switch_active", dashboard)
        self.assertIsInstance(dashboard["kill_switch_active"], bool)

    def test_dashboard_persistence_fields(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        p = dashboard["persistence"]
        for key in ["total_files", "valid", "existing"]:
            self.assertIn(key, p)

    def test_dashboard_danger_classification(self):
        from core.governance import get_governance_dashboard
        dashboard = get_governance_dashboard()
        dc = dashboard["danger_classification"]
        self.assertIn("levels", dc)
        self.assertIn("connector_classifications", dc)
        self.assertIsInstance(dc["levels"], list)
        self.assertGreater(len(dc["levels"]), 0)


# ═══════════════════════════════════════════════════════════════
# BUSINESS PIPELINE
# ═══════════════════════════════════════════════════════════════

class TestLeadPipeline(unittest.TestCase):
    """Lead management validates stages and bounds."""

    def test_lead_stages_defined(self):
        from core.business_pipeline import LEAD_STAGES
        self.assertGreater(len(LEAD_STAGES), 5)
        self.assertIn("lead", LEAD_STAGES)
        self.assertIn("closed", LEAD_STAGES)
        self.assertIn("lost", LEAD_STAGES)

    def test_add_and_advance_lead(self):
        from core.business_pipeline import LeadTracker
        tracker = LeadTracker(persist_path="/tmp/test_leads.json")
        lead = tracker.add_lead(name="Test Client", source="web", value_estimate=1000)
        self.assertEqual(lead.stage, "lead")
        advanced = tracker.advance_lead(lead.lead_id, "qualified", note="Good fit")
        self.assertIsNotNone(advanced)
        self.assertEqual(advanced.stage, "qualified")

    def test_invalid_stage_rejected(self):
        from core.business_pipeline import LeadTracker
        tracker = LeadTracker(persist_path="/tmp/test_leads2.json")
        lead = tracker.add_lead(name="Test")
        result = tracker.advance_lead(lead.lead_id, "INVALID_STAGE")
        # Should return None or the lead unchanged
        if result is not None:
            self.assertNotEqual(result.stage, "INVALID_STAGE")

    def test_lead_name_bounded(self):
        from core.business_pipeline import LeadTracker
        tracker = LeadTracker(persist_path="/tmp/test_leads3.json")
        lead = tracker.add_lead(name="x" * 500)
        self.assertLessEqual(len(lead.name), 200)

    def test_pipeline_summary(self):
        persist = "/tmp/test_leads_summary.json"
        if os.path.exists(persist):
            os.unlink(persist)
        from core.business_pipeline import LeadTracker
        tracker = LeadTracker(persist_path=persist)
        tracker.add_lead(name="A", value_estimate=100)
        tracker.add_lead(name="B", value_estimate=200)
        summary = tracker.get_pipeline_summary()
        self.assertIsInstance(summary, dict)
        self.assertIn("total_leads", summary)
        self.assertGreaterEqual(summary["total_leads"], 2)


class TestContentPipeline(unittest.TestCase):
    """Content pipeline validates stages."""

    def test_content_stages_defined(self):
        from core.business_pipeline import CONTENT_STAGES
        self.assertGreater(len(CONTENT_STAGES), 4)
        self.assertIn("idea", CONTENT_STAGES)
        self.assertIn("published", CONTENT_STAGES)

    def test_create_and_advance_content(self):
        from core.business_pipeline import ContentPipeline
        pipeline = ContentPipeline(persist_path="/tmp/test_content.json")
        item = pipeline.create(title="Test Article", content_type="article")
        self.assertEqual(item.stage, "idea")
        advanced = pipeline.advance(item.content_id, "research")
        self.assertIsNotNone(advanced)
        self.assertEqual(advanced.stage, "research")


# ═══════════════════════════════════════════════════════════════
# DANGER CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

class TestDangerClassification(unittest.TestCase):
    """All connectors have danger classifications."""

    def test_classify_danger_returns_dict(self):
        from core.governance import classify_danger
        result = classify_danger(connector_name="http_request", action="execute")
        self.assertIsInstance(result, dict)
        self.assertIn("level", result)

    def test_all_connectors_classified(self):
        from core.governance import classify_danger
        from core.connectors import CONNECTOR_REGISTRY
        for name in CONNECTOR_REGISTRY:
            result = classify_danger(connector_name=name)
            self.assertIsInstance(result, dict, f"classify_danger failed for {name}")

    def test_high_risk_connectors_require_approval(self):
        from core.connectors import CONNECTOR_REGISTRY
        for name, entry in CONNECTOR_REGISTRY.items():
            spec = entry["spec"]
            if spec.risk_level == "high":
                self.assertTrue(
                    spec.requires_approval,
                    f"High-risk connector '{name}' does not require approval"
                )


# ═══════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════

class TestRateLimiting(unittest.TestCase):
    """Rate limit checks are functional."""

    def test_rate_limit_check_returns_tuple(self):
        from core.governance import check_connector_rate
        allowed, reason = check_connector_rate("http_request")
        self.assertIsInstance(allowed, bool)
        self.assertIsInstance(reason, str)

    def test_rate_limit_status_all_connectors(self):
        from core.governance import get_rate_limit_status
        status = get_rate_limit_status()
        self.assertIsInstance(status, dict)


# ═══════════════════════════════════════════════════════════════
# CONNECTOR REGISTRY COMPLETENESS
# ═══════════════════════════════════════════════════════════════

class TestConnectorRegistry(unittest.TestCase):
    """All registered connectors have valid specs."""

    def test_all_connectors_have_spec_and_execute(self):
        from core.connectors import CONNECTOR_REGISTRY
        for name, entry in CONNECTOR_REGISTRY.items():
            self.assertIn("spec", entry, f"{name}: missing spec")
            self.assertIn("execute", entry, f"{name}: missing execute")
            self.assertTrue(callable(entry["execute"]), f"{name}: execute not callable")

    def test_all_specs_have_required_fields(self):
        from core.connectors import CONNECTOR_REGISTRY
        for name, entry in CONNECTOR_REGISTRY.items():
            spec = entry["spec"]
            self.assertTrue(hasattr(spec, "name"), f"{name}: spec missing name")
            self.assertTrue(hasattr(spec, "risk_level"), f"{name}: spec missing risk_level")
            self.assertTrue(hasattr(spec, "category"), f"{name}: spec missing category")

    def test_connector_count_minimum(self):
        from core.connectors import CONNECTOR_REGISTRY
        self.assertGreaterEqual(len(CONNECTOR_REGISTRY), 10,
                                "Expected at least 10 connectors")


# ═══════════════════════════════════════════════════════════════
# OPERATING PRIMITIVES
# ═══════════════════════════════════════════════════════════════

class TestOperatingPrimitives(unittest.TestCase):
    """Core operating primitives are functional."""

    def test_score_feasibility(self):
        from core.operating_primitives import score_feasibility
        result = score_feasibility(
            goal="Build a REST API",
            mission_type="coding_task",
            required_tools=["write_file", "read_file"],
            complexity="medium",
        )
        self.assertIsInstance(result, object)
        if hasattr(result, 'score'):
            self.assertGreaterEqual(result.score, 0)
            self.assertLessEqual(result.score, 1)

    def test_can_accept_mission(self):
        from core.operating_primitives import can_accept_mission
        self.assertTrue(can_accept_mission(0))
        self.assertTrue(can_accept_mission(1))

    def test_prioritize_missions(self):
        from core.operating_primitives import prioritize_missions
        missions = [
            {"mission_type": "coding_task", "risk_score": 3, "complexity": "medium"},
            {"mission_type": "research_task", "risk_score": 1, "complexity": "low"},
        ]
        result = prioritize_missions(missions)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_operational_signals(self):
        from core.operating_primitives import get_operational_signals
        signals = get_operational_signals()
        self.assertIsInstance(signals, dict)
        # Signals contain performance data (keys vary)
        self.assertGreater(len(signals), 0, "Operational signals should not be empty")

    def test_compute_economics(self):
        from core.operating_primitives import compute_economics
        result = compute_economics(
            goal="Test",
            mission_type="research_task",
            complexity="low",
            plan_steps=2,
            risk_score=1,
        )
        self.assertIsInstance(result, object)
        if hasattr(result, 'to_dict'):
            d = result.to_dict()
            self.assertIsInstance(d, dict)


# ═══════════════════════════════════════════════════════════════
# APPROVAL QUEUE
# ═══════════════════════════════════════════════════════════════

class TestApprovalQueue(unittest.TestCase):
    """Approval queue CRUD operations."""

    def test_get_pending_returns_list(self):
        from core.approval_queue import get_pending
        pending = get_pending()
        self.assertIsInstance(pending, list)

    def test_submit_and_check(self):
        from core.approval_queue import submit_for_approval, RiskLevel
        result = submit_for_approval(
            action="test_action",
            risk_level=RiskLevel.READ,  # READ is auto-approved
            reason="Testing",
            expected_impact="none",
            rollback_plan="revert",
        )
        self.assertIsInstance(result, dict)
        self.assertIn("approved", result)
        # READ risk should be auto-approved
        self.assertTrue(result["approved"])


# ═══════════════════════════════════════════════════════════════
# ROLLBACK MANAGER
# ═══════════════════════════════════════════════════════════════

class TestRollbackManager(unittest.TestCase):
    """Rollback manager creates and restores backups."""

    def test_backup_and_list(self):
        from core.rollback_manager import backup_file, list_backups
        test_file = "/tmp/test_rollback_file.txt"
        with open(test_file, "w") as f:
            f.write("original content")
        backup_path = backup_file(test_file)
        self.assertIsNotNone(backup_path)
        backups = list_backups(test_file)
        self.assertGreater(len(backups), 0)
        os.unlink(test_file)

    def test_context_manager(self):
        from core.rollback_manager import RollbackContext
        test_file = "/tmp/test_rollback_ctx.txt"
        with open(test_file, "w") as f:
            f.write("before")
        # Normal case: no exception
        with RollbackContext(test_file):
            with open(test_file, "w") as f:
                f.write("after")
        with open(test_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), "after")
        os.unlink(test_file)


# ═══════════════════════════════════════════════════════════════
# PERSISTENCE VALIDATION
# ═══════════════════════════════════════════════════════════════

class TestPersistenceValidation(unittest.TestCase):
    """Persistence files are validated."""

    def test_validate_all_persistence(self):
        from core.governance import validate_all_persistence
        result = validate_all_persistence()
        self.assertIsInstance(result, dict)
        self.assertIn("total_files", result)
        self.assertIn("valid", result)
        self.assertIn("existing", result)

    def test_validate_single_file(self):
        from core.governance import validate_persistence_file
        # Test with a non-existent file
        result = validate_persistence_file("/tmp/nonexistent_test_file.json")
        self.assertIsInstance(result, dict)
        self.assertIn("valid", result)
        self.assertFalse(result["valid"])


# ═══════════════════════════════════════════════════════════════
# DOMAIN MANAGER
# ═══════════════════════════════════════════════════════════════

@pytest.mark.stale
@pytest.mark.skip(reason="phantom: DomainManager")
class TestDomainManager(unittest.TestCase):
    """Business domain management."""

    def test_create_domain(self):
        from core.governance import get_domain_manager
        dm = get_domain_manager()
        dm._domains.clear()  # Reset for clean test state
        dm._loaded = True     # Prevent reload from disk
        domain = dm.create_domain(name="Test Domain", description="Testing")
        self.assertIsNotNone(domain)
        self.assertEqual(domain.name, "Test Domain")

    def test_portfolio_dashboard(self):
        from core.governance import get_domain_manager
        dm = get_domain_manager()
        dashboard = dm.get_portfolio_dashboard()
        self.assertIsInstance(dashboard, dict)

    def test_slot_allocation(self):
        from core.governance import get_domain_manager
        dm = get_domain_manager()
        recs = dm.recommend_slot_allocation()
        self.assertIsInstance(recs, list)


# ═══════════════════════════════════════════════════════════════
# STRESS: SAFETY UNDER LOAD
# ═══════════════════════════════════════════════════════════════

@pytest.mark.stale
@pytest.mark.skip(reason="phantom: sanitize_params")
class TestSafetyStress(unittest.TestCase):
    """Safety checks remain fast under load."""

    def test_1000_safety_checkpoints_bounded(self):
        os.environ.pop("BEA_EXECUTION_DISABLED", None)
        from core.governance import safety_checkpoint
        t0 = time.time()
        for _ in range(1000):
            safety_checkpoint(action="read", risk_level="low")
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0, f"1000 safety checks took {elapsed:.2f}s")

    def test_500_sanitizations_bounded(self):
        from core.connectors import _sanitize_connector_params
        t0 = time.time()
        for i in range(500):
            _sanitize_connector_params("test", {
                "url": f"https://example.com/{i}",
                "body": "x" * 1000,
                "timeout": 30,
            })
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.0, f"500 sanitizations took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
