"""tests/test_business_tools.py — Business tools + goal decomposition + registry tests."""
import json
import os
import sys
import unittest
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import types
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


# ── Generators ────────────────────────────────────────────────────────────────

class TestMarkdownGenerator(unittest.TestCase):

    def test_missing_title(self):
        from core.tools.generators import MarkdownGenerator
        t = MarkdownGenerator()
        r = t.execute(title="")
        self.assertFalse(r.ok)

    def test_generate_basic(self):
        from core.tools.generators import MarkdownGenerator
        t = MarkdownGenerator()
        r = t.execute(title="Test Doc", sections=[
            {"heading": "Intro", "content": "Hello world"},
            {"heading": "Details", "content": "More info"},
        ])
        self.assertTrue(r.ok)
        self.assertIn("# Test Doc", r.result)
        self.assertIn("## Intro", r.result)

    def test_string_sections(self):
        from core.tools.generators import MarkdownGenerator
        t = MarkdownGenerator()
        r = t.execute(title="Simple", sections=["paragraph one", "paragraph two"])
        self.assertTrue(r.ok)
        self.assertIn("paragraph one", r.result)


class TestHtmlGenerator(unittest.TestCase):

    def test_missing_title(self):
        from core.tools.generators import HtmlGenerator
        t = HtmlGenerator()
        r = t.execute(title="")
        self.assertFalse(r.ok)

    def test_generate_page(self):
        from core.tools.generators import HtmlGenerator
        t = HtmlGenerator()
        r = t.execute(title="Landing Page", body_sections=[
            {"tag": "h2", "content": "Welcome"},
            {"tag": "p", "content": "Visit our site"},
        ])
        self.assertTrue(r.ok)
        self.assertIn("<!DOCTYPE html>", r.result)
        self.assertIn("Landing Page", r.result)
        self.assertIn("Welcome", r.result)

    def test_default_css(self):
        from core.tools.generators import HtmlGenerator
        t = HtmlGenerator()
        r = t.execute(title="Styled", body_sections=["content"])
        self.assertIn("font-family", r.result)


class TestJsonSchemaGenerator(unittest.TestCase):

    def test_missing_name(self):
        from core.tools.generators import JsonSchemaGenerator
        t = JsonSchemaGenerator()
        r = t.execute(schema_name="")
        self.assertFalse(r.ok)

    def test_generate_schema(self):
        from core.tools.generators import JsonSchemaGenerator
        t = JsonSchemaGenerator()
        r = t.execute(
            schema_name="Contact",
            fields=[
                {"name": "name", "type": "string", "description": "Full name", "required": True},
                {"name": "email", "type": "string", "description": "Email address"},
                {"name": "age", "type": "integer"},
            ],
        )
        self.assertTrue(r.ok)
        schema = json.loads(r.result)
        self.assertEqual(schema["title"], "Contact")
        self.assertIn("name", schema["properties"])
        self.assertEqual(schema["properties"]["name"]["type"], "string")
        self.assertIn("name", schema["required"])

    def test_enum_field(self):
        from core.tools.generators import JsonSchemaGenerator
        t = JsonSchemaGenerator()
        r = t.execute(
            schema_name="Status",
            fields=[{"name": "status", "type": "string", "enum": ["active", "inactive"]}],
        )
        schema = json.loads(r.result)
        self.assertEqual(schema["properties"]["status"]["enum"], ["active", "inactive"])


class TestHttpTestTool(unittest.TestCase):

    def test_missing_url(self):
        from core.tools.generators import HttpTestTool
        t = HttpTestTool()
        r = t.execute(url="")
        self.assertFalse(r.ok)

    def test_invalid_url(self):
        from core.tools.generators import HttpTestTool
        t = HttpTestTool()
        r = t.execute(url="ftp://bad")
        self.assertFalse(r.ok)

    def test_schema(self):
        from core.tools.generators import HttpTestTool
        t = HttpTestTool()
        s = t.capability_schema()
        self.assertEqual(s["name"], "http_test")
        self.assertEqual(s["risk_level"], "LOW")


# ── Goal Decomposition ───────────────────────────────────────────────────────

@pytest.mark.stale
@pytest.mark.skip(reason="core.goal_decomposer module not implemented")
class TestGoalDecomposer(unittest.TestCase):

    def test_detect_website(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("create a landing page for plumber"), "website")

    def test_detect_document(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("generate a PDF report"), "document")

    def test_detect_data(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("extract data from JSON API"), "data")

    def test_detect_email(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("send an email newsletter"), "email")

    def test_detect_research(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("research market competitors"), "research")

    def test_detect_unknown(self):
        from core.goal_decomposer import detect_goal_type
        self.assertEqual(detect_goal_type("do something random"), "general")

    def test_decompose_website(self):
        from core.goal_decomposer import decompose
        result = decompose("create a website for a plumber")
        self.assertEqual(result.goal_type, "website")
        self.assertGreater(len(result.steps), 3)
        self.assertIn("html_generate", result.tools_needed)

    def test_decompose_document(self):
        from core.goal_decomposer import decompose
        result = decompose("write a summary report about AI trends")
        self.assertEqual(result.goal_type, "document")
        self.assertIn("markdown_generate", result.tools_needed)

    def test_decompose_to_plan(self):
        from core.goal_decomposer import decompose
        result = decompose("create landing page")
        plan = result.to_plan()
        self.assertIn("steps", plan)
        self.assertIn("goal", plan)
        self.assertTrue(all("action" in s for s in plan["steps"]))

    def test_decompose_to_dict(self):
        from core.goal_decomposer import decompose
        result = decompose("extract data from URL")
        d = result.to_dict()
        self.assertIn("step_count", d)
        self.assertIn("goal_type", d)

    def test_step_dependencies(self):
        from core.goal_decomposer import decompose
        result = decompose("create a website")
        # First step has no dependencies
        self.assertEqual(result.steps[0].depends_on, [])
        # Later steps depend on previous
        if len(result.steps) > 1:
            self.assertGreater(len(result.steps[1].depends_on), 0)


# ── Capability Registry (new tools) ──────────────────────────────────────────

class TestRegistryExpansion(unittest.TestCase):

    def test_email_registered(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        cap = r.get("email_send")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.risk_level, "MEDIUM")
        self.assertTrue(cap.requires_approval)

    def test_http_request_registered(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        self.assertTrue(r.is_registered("http_request"))

    def test_http_test_registered(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        self.assertTrue(r.is_registered("http_test"))

    def test_generators_registered(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        for name in ["markdown_generate", "html_generate", "json_schema_generate"]:
            self.assertTrue(r.is_registered(name), f"{name} not registered")

    def test_total_capabilities(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        stats = r.stats()
        self.assertGreaterEqual(stats["total"], 16)

    def test_email_requires_approval(self):
        from core.capabilities.registry import get_capability_registry
        r = get_capability_registry()
        perm = r.check_permission("email_send")
        self.assertTrue(perm["allowed"])
        self.assertTrue(perm["requires_approval"])


# ── Evaluation Scenarios ─────────────────────────────────────────────────────

@pytest.mark.stale
@pytest.mark.skip(reason="core.goal_decomposer module not implemented")
class TestEvaluationScenarios(unittest.TestCase):
    """Verify the AI-OS can plan real business workflows end-to-end."""

    def test_scenario_landing_page(self):
        """Scenario 1: Bea can decompose and plan a landing page creation."""
        from core.goal_decomposer import decompose
        result = decompose("create a landing page for a local plumber in Paris")
        plan = result.to_plan()
        self.assertGreater(len(plan["steps"]), 3)
        tools = {s["tool"] for s in plan["steps"]}
        self.assertTrue(tools & {"html_generate", "markdown_generate"})

    def test_scenario_structured_json(self):
        """Scenario 4: Generate structured JSON output."""
        from core.tools.generators import JsonSchemaGenerator
        t = JsonSchemaGenerator()
        r = t.execute(
            schema_name="BusinessContact",
            fields=[
                {"name": "company", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": True},
                {"name": "phone", "type": "string"},
                {"name": "industry", "type": "string", "enum": ["tech", "retail", "services"]},
            ],
        )
        self.assertTrue(r.ok)
        schema = json.loads(r.result)
        self.assertEqual(len(schema["properties"]), 4)
        self.assertIn("company", schema["required"])

    def test_scenario_api_call_plan(self):
        """Scenario 3: Plan for calling a public API."""
        from core.goal_decomposer import decompose
        result = decompose("call the OpenWeatherMap API to get Paris weather")
        self.assertIn("http_test", result.tools_needed)

    def test_scenario_document_generation(self):
        """Scenario 2: Generate a structured document."""
        from core.tools.generators import MarkdownGenerator
        t = MarkdownGenerator()
        r = t.execute(
            title="Q1 2026 Business Report",
            sections=[
                {"heading": "Executive Summary", "content": "Revenue up 15% YoY."},
                {"heading": "Key Metrics", "content": "ARR: €2.4M, Churn: 3.2%"},
                {"heading": "Next Steps", "content": "Expand to German market."},
            ],
        )
        self.assertTrue(r.ok)
        self.assertIn("Executive Summary", r.result)
        self.assertIn("€2.4M", r.result)


if __name__ == "__main__":
    unittest.main()
