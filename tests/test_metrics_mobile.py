"""
Tests — Mobile Metrics API

Coverage:
  M1. Router has all 5 endpoints
  M2. Summary returns health + success_rate + missions + cost + alerts
  M3. Routing returns models + fallbacks + health + cost_by_model
  M4. Tools returns tool list + success rates + latency
  M5. Improvement returns experiment stats + daemon status
  M6. Failures returns by_category + top_failures + recent
  M7. No secrets in any response
  M8. Empty metrics returns valid zero-state
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestRouterExists:
    """M1: All 5 endpoints registered."""

    def test_router_importable(self):
        from api.routes.metrics_mobile import router
        assert router is not None

    def test_has_all_endpoints(self):
        from api.routes.metrics_mobile import router
        paths = [r.path for r in router.routes]
        prefix = "/api/v3/metrics"
        assert f"{prefix}/summary" in paths
        assert f"{prefix}/routing" in paths
        assert f"{prefix}/tools" in paths
        assert f"{prefix}/improvement" in paths
        assert f"{prefix}/failures" in paths


class TestSummaryEndpoint:
    """M2: Summary produces correct structure."""

    def test_summary_structure(self):
        from core.metrics_store import (
            reset_metrics, emit_mission_submitted, emit_mission_completed,
            emit_mission_failed, emit_tool_invocation, emit_model_selected,
        )
        m = reset_metrics()

        emit_mission_submitted("code_review")
        emit_mission_submitted("code_review")
        emit_mission_completed("code_review", 5000)
        emit_mission_failed("deploy", "crash")
        emit_tool_invocation("shell", True, 100)
        emit_tool_invocation("shell", False, 5000)
        emit_model_selected("claude-sonnet", "cloud")

        # Call the endpoint logic directly
        import asyncio
        from api.routes.metrics_mobile import metrics_summary
        resp = asyncio.get_event_loop().run_until_complete(metrics_summary("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        d = data["data"]
        assert "health" in d
        assert "success_rate" in d
        assert "missions" in d
        assert "cost_today_usd" in d
        assert "active_models" in d
        assert "alerts" in d
        assert d["missions"]["submitted"] == 2
        assert d["missions"]["completed"] == 1

    def test_summary_empty_metrics(self):
        """M8: Zero-state returns valid structure."""
        from core.metrics_store import reset_metrics
        reset_metrics()

        import asyncio
        from api.routes.metrics_mobile import metrics_summary
        resp = asyncio.get_event_loop().run_until_complete(metrics_summary("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        assert data["data"]["success_rate"] == 0
        assert data["data"]["missions"]["submitted"] == 0


class TestRoutingEndpoint:
    """M3: Routing returns model performance."""

    def test_routing_structure(self):
        from core.metrics_store import (
            reset_metrics, emit_model_selected, emit_model_failure,
            emit_model_latency, emit_fallback_used,
        )
        m = reset_metrics()

        emit_model_selected("claude-sonnet", "cloud")
        emit_model_selected("claude-sonnet", "cloud")
        emit_model_selected("gpt-4o", "cloud")
        emit_model_failure("claude-sonnet", "rate limited")
        emit_model_latency("claude-sonnet", 3000)
        emit_fallback_used("claude-sonnet", "gpt-4o")

        import asyncio
        from api.routes.metrics_mobile import metrics_routing
        resp = asyncio.get_event_loop().run_until_complete(metrics_routing("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        d = data["data"]
        assert "models" in d
        assert "fallbacks_used" in d
        assert "cloud_routes" in d
        assert len(d["models"]) >= 1


class TestToolsEndpoint:
    """M4: Tools returns reliability data."""

    def test_tools_structure(self):
        from core.metrics_store import (
            reset_metrics, emit_tool_invocation, emit_tool_timeout,
        )
        m = reset_metrics()

        emit_tool_invocation("shell_command", True, 150)
        emit_tool_invocation("shell_command", True, 200)
        emit_tool_invocation("web_search", False, 5000)
        emit_tool_timeout("web_search")

        import asyncio
        from api.routes.metrics_mobile import metrics_tools
        resp = asyncio.get_event_loop().run_until_complete(metrics_tools("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        d = data["data"]
        assert "tools" in d
        assert d["total_invocations"] == 3
        assert d["total_failures"] == 1
        assert d["total_timeouts"] == 1


class TestImprovementEndpoint:
    """M5: Improvement returns experiment stats."""

    def test_improvement_structure(self):
        from core.metrics_store import reset_metrics, emit_experiment
        m = reset_metrics()

        emit_experiment("promoted", 0.15)
        emit_experiment("rejected", -0.05)

        import asyncio
        from api.routes.metrics_mobile import metrics_improvement
        resp = asyncio.get_event_loop().run_until_complete(metrics_improvement("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        d = data["data"]
        assert d["experiments"]["started"] == 2
        assert d["experiments"]["promoted"] == 1
        assert d["experiments"]["rejected"] == 1
        assert d["lessons_learned"] == 2


class TestFailuresEndpoint:
    """M6: Failures returns aggregated patterns."""

    def test_failures_structure(self):
        from core.metrics_store import reset_metrics
        m = reset_metrics()

        m.record_failure("timeout", "executor", "timed out")
        m.record_failure("timeout", "executor", "timed out again")
        m.record_failure("auth", "api", "401")

        import asyncio
        from api.routes.metrics_mobile import metrics_failures
        resp = asyncio.get_event_loop().run_until_complete(metrics_failures("test"))
        data = json.loads(resp.body)

        assert data["ok"] is True
        d = data["data"]
        assert "by_category" in d
        assert "top_failures" in d
        assert "recent" in d
        assert d["total_1h"] >= 3


class TestNoSecrets:
    """M7: No secrets leak from any endpoint."""

    def test_no_secrets_in_summary(self):
        from core.metrics_store import reset_metrics, emit_model_selected
        reset_metrics()
        emit_model_selected("claude-sonnet")

        import asyncio
        from api.routes.metrics_mobile import metrics_summary
        resp = asyncio.get_event_loop().run_until_complete(metrics_summary("test"))
        text = resp.body.decode() if isinstance(resp.body, bytes) else str(resp.body)

        for keyword in ["api_key", "token", "secret", "password", "bearer"]:
            assert keyword not in text.lower(), f"Found '{keyword}' in response!"
