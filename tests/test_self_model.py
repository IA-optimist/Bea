"""
Tests — Self-Model Layer (60 tests)

Model Structure
  SM01. SelfModel has all 5 dimensions
  SM02. CapabilityEntry has required fields
  SM03. ComponentEntry has required fields
  SM04. HealthSignal has required fields
  SM05. ModificationBoundary has required fields
  SM06. AutonomyEnvelope has required fields
  SM07. CapabilityStatus enum values
  SM08. ComponentStatus enum values
  SM09. HealthStatus enum values
  SM10. AutonomyMode enum values

Serialization
  SM11. CapabilityEntry.to_dict includes reliability
  SM12. ComponentEntry.to_dict preserves status
  SM13. SelfModel.to_dict complete
  SM14. AutonomyEnvelope.to_dict all flags

Updater
  SM15. build_self_model returns SelfModel
  SM16. build_self_model populates capabilities
  SM17. build_self_model populates components
  SM18. build_self_model populates health signals
  SM19. build_self_model populates boundaries
  SM20. build_self_model populates autonomy
  SM21. build_self_model sets generation_duration_ms
  SM22. build_self_model fail-open on broken source
  SM23. _map_capability_status disabled → unavailable
  SM24. _map_capability_status requires_approval → approval_required
  SM25. _map_capability_status normal → ready
  SM26. _build_health contains auth_system
  SM27. _build_health contains cognitive_graph
  SM28. _build_boundaries has 3 zones

Queries
  SM29. what_can_i_do returns ready only
  SM30. what_cannot_i_do returns unavailable only
  SM31. what_is_degraded returns degraded
  SM32. what_requires_approval returns approval_required
  SM33. what_requires_configuration returns not_configured
  SM34. what_is_unsafe_to_modify returns restricted + forbidden
  SM35. what_is_reliable filters by min_reliability
  SM36. what_is_unstable filters by max_reliability
  SM37. what_is_missing returns unavailable + unknown
  SM38. readiness_score returns 0.0-1.0
  SM39. readiness_score all-ready = high
  SM40. readiness_score all-unavailable = low
  SM41. capability_summary counts
  SM42. component_summary counts
  SM43. health_summary counts

Serializer
  SM44. to_full_dict includes summary
  SM45. to_compact is small dict
  SM46. to_health_card has readiness_score
  SM47. to_llm_context is string
  SM48. to_llm_context contains Ready Capabilities
  SM49. to_llm_context contains Autonomy Flags

Sources
  SM50. read_capability_graph returns list
  SM51. read_mcp_registry returns list
  SM52. read_protected_paths returns dict with files/dirs/patterns
  SM53. probe_auth_health returns dict with healthy key
  SM54. probe_si_pipeline_health returns dict
  SM55. read_autonomy_config returns dict

API Routes
  SM56. self_model_router mounted
  SM57. /api/v3/self-model route exists
  SM58. /api/v3/self-model/compact route exists
  SM59. /api/v3/self-model/llm-context route exists
  SM60. /api/v3/self-model/readiness route exists
"""
import os
import sys
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# 1 — Model Structure
# ═══════════════════════════════════════════════════════════════

class TestModelStructure:

    def test_SM01_self_model_dimensions(self):
        """SM01."""
        from core.self_model.model import SelfModel
        m = SelfModel()
        assert hasattr(m, "capabilities")
        assert hasattr(m, "components")
        assert hasattr(m, "health")
        assert hasattr(m, "boundaries")
        assert hasattr(m, "autonomy")

    def test_SM02_capability_entry_fields(self):
        """SM02."""
        from core.self_model.model import CapabilityEntry, CapabilityStatus
        c = CapabilityEntry(id="test", status=CapabilityStatus.READY)
        assert c.id == "test"
        assert c.status == CapabilityStatus.READY
        assert hasattr(c, "confidence")
        assert hasattr(c, "source")
        assert hasattr(c, "dependencies")
        assert hasattr(c, "risk_level")
        assert hasattr(c, "last_success_ts")
        assert hasattr(c, "usage_count")

    def test_SM03_component_entry_fields(self):
        """SM03."""
        from core.self_model.model import ComponentEntry, ComponentStatus
        c = ComponentEntry(id="mcp-test", status=ComponentStatus.READY)
        assert c.id == "mcp-test"
        assert hasattr(c, "type")
        assert hasattr(c, "required_secrets")
        assert hasattr(c, "missing_secrets")
        assert hasattr(c, "spawnable")
        assert hasattr(c, "trust_level")

    def test_SM04_health_signal_fields(self):
        """SM04."""
        from core.self_model.model import HealthSignal, HealthStatus
        h = HealthSignal(name="test", status=HealthStatus.HEALTHY)
        assert h.name == "test"
        assert hasattr(h, "detail")
        assert hasattr(h, "checked_at")

    def test_SM05_modification_boundary_fields(self):
        """SM05."""
        from core.self_model.model import ModificationBoundary, ModificationZone
        b = ModificationBoundary(zone=ModificationZone.ALLOWED)
        assert hasattr(b, "description")
        assert hasattr(b, "paths")
        assert hasattr(b, "examples")

    def test_SM06_autonomy_envelope_fields(self):
        """SM06."""
        from core.self_model.model import AutonomyEnvelope
        a = AutonomyEnvelope()
        assert hasattr(a, "mode")
        assert hasattr(a, "requires_approval_for_tools")
        assert hasattr(a, "requires_approval_for_code_patch")
        assert hasattr(a, "requires_approval_for_external_calls")
        assert hasattr(a, "requires_approval_for_deployment")
        assert hasattr(a, "max_risk_auto_approve")
        assert hasattr(a, "max_files_per_patch")
        assert hasattr(a, "max_steps_per_mission")

    def test_SM07_capability_status_values(self):
        """SM07."""
        from core.self_model.model import CapabilityStatus
        expected = {"ready", "degraded", "unavailable", "approval_required",
                    "experimental", "not_configured"}
        actual = {s.value for s in CapabilityStatus}
        assert expected == actual

    def test_SM08_component_status_values(self):
        """SM08."""
        from core.self_model.model import ComponentStatus
        expected = {"ready", "disabled", "not_configured", "missing_secret",
                    "error", "approval_required", "unavailable"}
        actual = {s.value for s in ComponentStatus}
        assert expected == actual

    def test_SM09_health_status_values(self):
        """SM09."""
        from core.self_model.model import HealthStatus
        assert set(s.value for s in HealthStatus) == {"healthy", "degraded", "unknown"}

    def test_SM10_autonomy_mode_values(self):
        """SM10."""
        from core.self_model.model import AutonomyMode
        expected = {"observe", "propose_only", "supervised_execute",
                    "sandbox_self_improve", "restricted_autonomous"}
        assert set(s.value for s in AutonomyMode) == expected


# ═══════════════════════════════════════════════════════════════
# 2 — Serialization
# ═══════════════════════════════════════════════════════════════

class TestSerialization:

    def test_SM11_capability_to_dict_reliability(self):
        """SM11."""
        from core.self_model.model import CapabilityEntry, CapabilityStatus
        c = CapabilityEntry(id="test", status=CapabilityStatus.READY,
                            usage_count=8, failure_count=2)
        d = c.to_dict()
        assert d["reliability"] == 0.8
        assert d["status"] == "ready"

    def test_SM12_component_to_dict(self):
        """SM12."""
        from core.self_model.model import ComponentEntry, ComponentStatus
        c = ComponentEntry(id="mcp-fs", status=ComponentStatus.READY)
        d = c.to_dict()
        assert d["status"] == "ready"
        assert d["id"] == "mcp-fs"

    def test_SM13_self_model_to_dict(self):
        """SM13."""
        from core.self_model.model import SelfModel
        m = SelfModel()
        d = m.to_dict()
        assert "capabilities" in d
        assert "components" in d
        assert "health" in d
        assert "boundaries" in d
        assert "autonomy" in d
        assert "version" in d

    def test_SM14_autonomy_to_dict(self):
        """SM14."""
        from core.self_model.model import AutonomyEnvelope
        a = AutonomyEnvelope()
        d = a.to_dict()
        assert "requires_approval_for_tools" in d
        assert "requires_approval_for_code_patch" in d
        assert "max_risk_auto_approve" in d


# ═══════════════════════════════════════════════════════════════
# 3 — Updater
# ═══════════════════════════════════════════════════════════════

class TestUpdater:

    def test_SM15_build_returns_self_model(self):
        """SM15."""
        from core.self_model.updater import build_self_model
        from core.self_model.model import SelfModel
        m = build_self_model()
        assert isinstance(m, SelfModel)

    def test_SM16_capabilities_populated(self):
        """SM16."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert isinstance(m.capabilities, dict)

    def test_SM17_components_populated(self):
        """SM17."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert isinstance(m.components, dict)

    def test_SM18_health_populated(self):
        """SM18."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert isinstance(m.health, dict)
        assert len(m.health) >= 3  # At least auth, cognitive, si_pipeline

    def test_SM19_boundaries_populated(self):
        """SM19."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert isinstance(m.boundaries, list)
        assert len(m.boundaries) >= 2  # At least allowed + restricted

    def test_SM20_autonomy_populated(self):
        """SM20."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert m.autonomy is not None
        assert m.autonomy.requires_approval_for_code_patch is True

    def test_SM21_generation_duration(self):
        """SM21."""
        from core.self_model.updater import build_self_model
        m = build_self_model()
        assert m.generation_duration_ms > 0

    def test_SM22_fail_open(self):
        """SM22."""
        from core.self_model.updater import build_self_model
        from unittest.mock import patch
        with patch("core.self_model.sources.read_capability_graph", side_effect=RuntimeError("boom")):
            m = build_self_model()
        assert isinstance(m.capabilities, dict)
        # Other dimensions still populated
        assert len(m.health) > 0

    def test_SM23_disabled_maps_unavailable(self):
        """SM23."""
        from core.self_model.updater import _map_capability_status
        from core.self_model.model import CapabilityStatus
        s = _map_capability_status({"constraints": ["disabled"]})
        assert s == CapabilityStatus.UNAVAILABLE

    def test_SM24_requires_approval_maps(self):
        """SM24."""
        from core.self_model.updater import _map_capability_status
        from core.self_model.model import CapabilityStatus
        s = _map_capability_status({"constraints": ["requires_approval"]})
        assert s == CapabilityStatus.APPROVAL_REQUIRED

    def test_SM25_normal_maps_ready(self):
        """SM25."""
        from core.self_model.updater import _map_capability_status
        from core.self_model.model import CapabilityStatus
        s = _map_capability_status({"constraints": []})
        assert s == CapabilityStatus.READY

    def test_SM26_health_has_auth(self):
        """SM26."""
        from core.self_model.updater import _build_health
        h = _build_health()
        assert "auth_system" in h

    def test_SM27_health_has_cognitive(self):
        """SM27."""
        from core.self_model.updater import _build_health
        h = _build_health()
        assert "cognitive_graph" in h

    def test_SM28_boundaries_three_zones(self):
        """SM28."""
        from core.self_model.updater import _build_boundaries
        b = _build_boundaries()
        zones = {bb.zone.value for bb in b}
        assert "allowed" in zones
        assert "restricted" in zones
        assert "forbidden" in zones


# ═══════════════════════════════════════════════════════════════
# 4 — Queries
# ═══════════════════════════════════════════════════════════════

class TestQueries:

    def _make_model(self):
        from core.self_model.model import (
            SelfModel, CapabilityEntry, CapabilityStatus,
            ComponentEntry, ComponentStatus,
            HealthSignal, HealthStatus,
            ModificationBoundary, ModificationZone,
        )
        m = SelfModel()
        m.capabilities = {
            "a": CapabilityEntry(id="a", status=CapabilityStatus.READY, usage_count=10),
            "b": CapabilityEntry(id="b", status=CapabilityStatus.UNAVAILABLE),
            "c": CapabilityEntry(id="c", status=CapabilityStatus.DEGRADED, confidence=0.3,
                                 usage_count=3, failure_count=7),
            "d": CapabilityEntry(id="d", status=CapabilityStatus.APPROVAL_REQUIRED, risk_level="high"),
            "e": CapabilityEntry(id="e", status=CapabilityStatus.NOT_CONFIGURED),
        }
        m.components = {
            "mcp1": ComponentEntry(id="mcp1", type="mcp", status=ComponentStatus.READY),
            "mcp2": ComponentEntry(id="mcp2", type="mcp", status=ComponentStatus.NOT_CONFIGURED,
                                   missing_secrets=["API_KEY"]),
            "mcp3": ComponentEntry(id="mcp3", type="mcp", status=ComponentStatus.ERROR, error="crash"),
        }
        m.health = {
            "auth": HealthSignal(name="auth", status=HealthStatus.HEALTHY),
            "docker": HealthSignal(name="docker", status=HealthStatus.DEGRADED, detail="timeout"),
            "unknown": HealthSignal(name="unknown", status=HealthStatus.UNKNOWN),
        }
        m.boundaries = [
            ModificationBoundary(zone=ModificationZone.ALLOWED),
            ModificationBoundary(zone=ModificationZone.RESTRICTED, paths=["core/meta_orchestrator.py"]),
            ModificationBoundary(zone=ModificationZone.FORBIDDEN, paths=[".env"]),
        ]
        return m

    def test_SM29_what_can_i_do(self):
        """SM29."""
        from core.self_model.queries import what_can_i_do
        result = what_can_i_do(self._make_model())
        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_SM30_what_cannot_i_do(self):
        """SM30."""
        from core.self_model.queries import what_cannot_i_do
        result = what_cannot_i_do(self._make_model())
        ids = {r["id"] for r in result}
        assert "b" in ids
        assert "e" in ids

    def test_SM31_what_is_degraded(self):
        """SM31."""
        from core.self_model.queries import what_is_degraded
        result = what_is_degraded(self._make_model())
        ids = {r["id"] for r in result}
        assert "c" in ids or "docker" in ids  # Capability or health

    def test_SM32_what_requires_approval(self):
        """SM32."""
        from core.self_model.queries import what_requires_approval
        result = what_requires_approval(self._make_model())
        ids = {r["id"] for r in result}
        assert "d" in ids

    def test_SM33_what_requires_configuration(self):
        """SM33."""
        from core.self_model.queries import what_requires_configuration
        result = what_requires_configuration(self._make_model())
        ids = {r["id"] for r in result}
        assert "mcp2" in ids
        assert result[0]["missing_secrets"] == ["API_KEY"]

    def test_SM34_what_is_unsafe_to_modify(self):
        """SM34."""
        from core.self_model.queries import what_is_unsafe_to_modify
        result = what_is_unsafe_to_modify(self._make_model())
        zones = {r["zone"] for r in result}
        assert "restricted" in zones
        assert "forbidden" in zones
        assert "allowed" not in zones

    def test_SM35_what_is_reliable(self):
        """SM35."""
        from core.self_model.queries import what_is_reliable
        result = what_is_reliable(self._make_model(), min_reliability=0.5)
        ids = {r["id"] for r in result}
        assert "a" in ids  # 10/10 = 1.0

    def test_SM36_what_is_unstable(self):
        """SM36."""
        from core.self_model.queries import what_is_unstable
        result = what_is_unstable(self._make_model(), max_reliability=0.5)
        ids = {r["id"] for r in result}
        assert "c" in ids  # 3/10 = 0.3

    def test_SM37_what_is_missing(self):
        """SM37."""
        from core.self_model.queries import what_is_missing
        result = what_is_missing(self._make_model())
        types = {r["type"] for r in result}
        assert "mcp" in types or "health" in types

    def test_SM38_readiness_score_range(self):
        """SM38."""
        from core.self_model.queries import readiness_score
        score = readiness_score(self._make_model())
        assert 0.0 <= score <= 1.0

    def test_SM39_readiness_all_ready(self):
        """SM39."""
        from core.self_model.model import (
            SelfModel, CapabilityEntry, CapabilityStatus,
            ComponentEntry, ComponentStatus,
            HealthSignal, HealthStatus,
        )
        from core.self_model.queries import readiness_score
        m = SelfModel()
        m.capabilities = {"a": CapabilityEntry(id="a", status=CapabilityStatus.READY)}
        m.components = {"b": ComponentEntry(id="b", status=ComponentStatus.READY)}
        m.health = {"c": HealthSignal(name="c", status=HealthStatus.HEALTHY)}
        assert readiness_score(m) == 1.0

    def test_SM40_readiness_all_unavailable(self):
        """SM40."""
        from core.self_model.model import (
            SelfModel, CapabilityEntry, CapabilityStatus,
            ComponentEntry, ComponentStatus,
            HealthSignal, HealthStatus,
        )
        from core.self_model.queries import readiness_score
        m = SelfModel()
        m.capabilities = {"a": CapabilityEntry(id="a", status=CapabilityStatus.UNAVAILABLE)}
        m.components = {"b": ComponentEntry(id="b", status=ComponentStatus.UNAVAILABLE)}
        m.health = {"c": HealthSignal(name="c", status=HealthStatus.DEGRADED)}
        assert readiness_score(m) == 0.0

    def test_SM41_capability_summary(self):
        """SM41."""
        from core.self_model.queries import capability_summary
        result = capability_summary(self._make_model())
        assert result["total"] == 5
        assert "ready" in result["by_status"]

    def test_SM42_component_summary(self):
        """SM42."""
        from core.self_model.queries import component_summary
        result = component_summary(self._make_model())
        assert result["total"] == 3

    def test_SM43_health_summary(self):
        """SM43."""
        from core.self_model.queries import health_summary
        result = health_summary(self._make_model())
        assert result["total"] == 3
        assert "healthy" in result["by_status"]


# ═══════════════════════════════════════════════════════════════
# 5 — Serializer
# ═══════════════════════════════════════════════════════════════

class TestSerializer:

    def test_SM44_to_full_dict_has_summary(self):
        """SM44."""
        from core.self_model.serializer import to_full_dict
        from core.self_model.updater import build_self_model
        d = to_full_dict(build_self_model())
        assert "summary" in d
        assert "readiness_score" in d["summary"]

    def test_SM45_to_compact_small(self):
        """SM45."""
        from core.self_model.serializer import to_compact
        from core.self_model.updater import build_self_model
        d = to_compact(build_self_model())
        assert "readiness" in d
        assert "autonomy" in d
        assert len(d) < 15  # Small dict

    def test_SM46_health_card_has_score(self):
        """SM46."""
        from core.self_model.serializer import to_health_card
        from core.self_model.updater import build_self_model
        d = to_health_card(build_self_model())
        assert "readiness_score" in d

    def test_SM47_llm_context_is_string(self):
        """SM47."""
        from core.self_model.serializer import to_llm_context
        from core.self_model.updater import build_self_model
        text = to_llm_context(build_self_model())
        assert isinstance(text, str)
        assert len(text) > 50

    def test_SM48_llm_context_has_sections(self):
        """SM48."""
        from core.self_model.serializer import to_llm_context
        from core.self_model.updater import build_self_model
        text = to_llm_context(build_self_model())
        assert "Readiness" in text or "Self-Model" in text

    def test_SM49_llm_context_has_autonomy(self):
        """SM49."""
        from core.self_model.serializer import to_llm_context
        from core.self_model.updater import build_self_model
        text = to_llm_context(build_self_model())
        assert "Autonomy" in text


# ═══════════════════════════════════════════════════════════════
# 6 — Sources
# ═══════════════════════════════════════════════════════════════

class TestSources:

    def test_SM50_read_capability_graph(self):
        """SM50."""
        from core.self_model.sources import read_capability_graph
        result = read_capability_graph()
        assert isinstance(result, list)

    def test_SM51_read_mcp_registry(self):
        """SM51."""
        from core.self_model.sources import read_mcp_registry
        result = read_mcp_registry()
        assert isinstance(result, list)

    def test_SM52_read_protected_paths(self):
        """SM52."""
        from core.self_model.sources import read_protected_paths
        result = read_protected_paths()
        assert "files" in result
        assert "dirs" in result
        assert "patterns" in result

    def test_SM53_probe_auth_health(self):
        """SM53."""
        from core.self_model.sources import probe_auth_health
        result = probe_auth_health()
        assert "healthy" in result

    def test_SM54_probe_si_pipeline_health(self):
        """SM54."""
        from core.self_model.sources import probe_si_pipeline_health
        result = probe_si_pipeline_health()
        assert "healthy" in result

    def test_SM55_read_autonomy_config(self):
        """SM55."""
        from core.self_model.sources import read_autonomy_config
        result = read_autonomy_config()
        assert "mode" in result
        assert "max_risk_auto" in result


# ═══════════════════════════════════════════════════════════════
# 7 — API Routes
# ═══════════════════════════════════════════════════════════════

class TestAPIRoutes:

    def test_SM56_router_mounted(self):
        """SM56."""
        from api.main import app
        paths = [r.path for r in app.routes]
        self_model_paths = [p for p in paths if "self-model" in p]
        assert len(self_model_paths) >= 1

    def test_SM57_main_route_exists(self):
        """SM57."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model" in paths

    def test_SM58_compact_route_exists(self):
        """SM58."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/compact" in paths

    def test_SM59_llm_context_route_exists(self):
        """SM59."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/llm-context" in paths

    def test_SM60_readiness_route_exists(self):
        """SM60."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/readiness" in paths


# ═══════════════════════════════════════════════════════════════
# 8 — Extended Queries
# ═══════════════════════════════════════════════════════════════

class TestExtendedQueries:

    def _make_model(self):
        from core.self_model.model import (
            SelfModel, CapabilityEntry, CapabilityStatus,
            ComponentEntry, ComponentStatus,
            HealthSignal, HealthStatus,
        )
        m = SelfModel()
        m.capabilities = {
            "code.patch": CapabilityEntry(
                id="code.patch", status=CapabilityStatus.READY,
                confidence=0.9, usage_count=10,
                dependencies=["mcp-fs"],
            ),
            "deploy.aws": CapabilityEntry(
                id="deploy.aws", status=CapabilityStatus.UNAVAILABLE,
                error="No AWS credentials",
            ),
            "security.audit": CapabilityEntry(
                id="security.audit", status=CapabilityStatus.APPROVAL_REQUIRED,
                risk_level="high", constraints=["requires_approval"],
            ),
            "unstable.tool": CapabilityEntry(
                id="unstable.tool", status=CapabilityStatus.DEGRADED,
                usage_count=3, failure_count=7,
            ),
        }
        m.components = {
            "mcp-fs": ComponentEntry(id="mcp-fs", type="mcp", status=ComponentStatus.READY),
            "mcp-pg": ComponentEntry(
                id="mcp-pg", type="mcp", status=ComponentStatus.UNAVAILABLE,
                reason="no binary",
            ),
            "mcp-hub": ComponentEntry(
                id="mcp-hub", type="mcp", status=ComponentStatus.NOT_CONFIGURED,
                missing_secrets=["HUBSPOT_API_KEY"],
            ),
        }
        m.health = {
            "auth": HealthSignal(name="auth", status=HealthStatus.HEALTHY),
            "docker": HealthSignal(name="docker", status=HealthStatus.DEGRADED, detail="timeout"),
        }
        return m

    def test_SM61_get_capability_confidence(self):
        """SM61."""
        from core.self_model.queries import get_capability_confidence
        m = self._make_model()
        assert get_capability_confidence(m, "code.patch") == 0.9
        assert get_capability_confidence(m, "nonexistent") == 0.0

    def test_SM62_get_tools_for_capability(self):
        """SM62."""
        from core.self_model.queries import get_tools_for_capability
        m = self._make_model()
        assert "mcp-fs" in get_tools_for_capability(m, "code.patch")
        assert get_tools_for_capability(m, "nonexistent") == []

    def test_SM63_get_blocked_capabilities(self):
        """SM63."""
        from core.self_model.queries import get_blocked_capabilities
        blocked = get_blocked_capabilities(self._make_model())
        ids = {b["id"] for b in blocked}
        assert "deploy.aws" in ids
        assert "security.audit" in ids
        assert "code.patch" not in ids  # Ready = not blocked

    def test_SM64_get_missing_dependencies(self):
        """SM64."""
        from core.self_model.queries import get_missing_dependencies
        # code.patch depends on mcp-fs which IS ready → no missing
        result = get_missing_dependencies(self._make_model())
        # mcp-pg is not ready but no capability depends on it
        assert isinstance(result, list)

    def test_SM65_get_runtime_health(self):
        """SM65."""
        from core.self_model.queries import get_runtime_health
        h = get_runtime_health(self._make_model())
        assert h["auth"] == "healthy"
        assert h["docker"] == "degraded"

    def test_SM66_get_autonomy_limits(self):
        """SM66."""
        from core.self_model.queries import get_autonomy_limits
        a = get_autonomy_limits(self._make_model())
        assert "mode" in a
        assert "tools_need_approval" in a
        assert a["tools_need_approval"] is True

    def test_SM67_get_known_limitations(self):
        """SM67."""
        from core.self_model.queries import get_known_limitations
        lims = get_known_limitations(self._make_model())
        assert isinstance(lims, list)
        assert len(lims) > 0
        # Should have MCP unavailable, missing secret, degraded health
        categories = {l["category"] for l in lims}
        assert "mcp" in categories or "health" in categories

    def test_SM68_limitations_sorted_by_severity(self):
        """SM68."""
        from core.self_model.queries import get_known_limitations
        lims = get_known_limitations(self._make_model())
        severities = [l["severity"] for l in lims]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        numeric = [order.get(s, 99) for s in severities]
        assert numeric == sorted(numeric)

    def test_SM69_limitations_have_source(self):
        """SM69."""
        from core.self_model.queries import get_known_limitations
        lims = get_known_limitations(self._make_model())
        for l in lims:
            assert "source" in l
            assert l["source"] != ""

    def test_SM70_limitations_no_secrets(self):
        """SM70."""
        from core.self_model.queries import get_known_limitations
        lims = get_known_limitations(self._make_model())
        text = str(lims).lower()
        assert "sk-" not in text
        assert "ghp_" not in text
        assert "password" not in text


# ═══════════════════════════════════════════════════════════════
# 9 — Extended API Routes
# ═══════════════════════════════════════════════════════════════

class TestExtendedAPIRoutes:

    def test_SM71_summary_route_exists(self):
        """SM71."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/summary" in paths

    def test_SM72_runtime_route_exists(self):
        """SM72."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/runtime" in paths

    def test_SM73_limitations_route_exists(self):
        """SM73."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/limitations" in paths

    def test_SM74_autonomy_route_exists(self):
        """SM74."""
        from api.main import app
        paths = [r.path for r in app.routes]
        assert "/api/v3/self-model/autonomy" in paths

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")),
        reason="static/self-model.html supprimé (consolidé dans app.html)",
    )
    def test_SM75_web_ui_exists(self):
        """SM75."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")
        assert os.path.isfile(path)

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")),
        reason="static/self-model.html supprimé (consolidé dans app.html)",
    )
    def test_SM76_web_ui_uses_auth(self):
        """SM76."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        assert "jarvis_token" in html
        assert "Authorization" in html

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")),
        reason="static/self-model.html supprimé (consolidé dans app.html)",
    )
    def test_SM77_web_ui_has_limitations(self):
        """SM77."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        assert "limitations" in html.lower()

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")),
        reason="static/self-model.html supprimé (consolidé dans app.html)",
    )
    def test_SM78_web_ui_has_autonomy(self):
        """SM78."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "static", "self-model.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        assert "autonomy" in html.lower()

    @pytest.mark.skipif(
        not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "static", "index.html")),
        reason="static/index.html supprimé (app.html est le SPA canonique)",
    )
    def test_SM79_nav_link_in_index(self):
        """SM79."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        assert "self-model.html" in html

    def test_SM80_total_self_model_routes(self):
        """SM80."""
        from api.main import app
        paths = [r.path for r in app.routes if "self-model" in r.path]
        assert len(paths) >= 10  # 7 original + 4 new
