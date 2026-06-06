"""Regression tests for extracting mission analysis helpers from core.mission_system."""

from pathlib import Path
import sys
import types

if "structlog" not in sys.modules:
    _structlog = types.ModuleType("structlog")
    _logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    _structlog.get_logger = lambda *args, **kwargs: _logger
    sys.modules["structlog"] = _structlog
def test_mission_analysis_has_dedicated_module_with_mission_system_compatibility():
    from core import mission_analysis
    from core import mission_system

    exported_names = [
        "CAPABILITY_DEMO",
        "MissionIntent",
        "classify_action",
        "compute_complexity",
        "compute_confidence_score",
        "compute_risk_score",
        "detect_intent",
        "evaluate_approval",
        "is_capability_query",
        "risk_score_to_level",
    ]

    for name in exported_names:
        assert getattr(mission_system, name) is getattr(mission_analysis, name)

    source = Path("core/mission_system.py").read_text(encoding="utf-8")
    for function_name in [
        "is_capability_query",
        "detect_intent",
        "classify_action",
        "compute_risk_score",
        "risk_score_to_level",
        "compute_complexity",
        "evaluate_approval",
        "compute_confidence_score",
    ]:
        assert f"def {function_name}" not in source
    assert "class MissionIntent" not in source


def test_mission_analysis_keeps_existing_classification_behaviour():
    from core.mission_analysis import (
        MissionIntent,
        classify_action,
        compute_complexity,
        compute_risk_score,
        detect_intent,
        evaluate_approval,
        risk_score_to_level,
    )

    assert detect_intent("inspect and audit this code") == MissionIntent.ANALYZE
    assert classify_action("create a new file") == ("write", "MEDIUM")
    assert compute_risk_score("delete docker deployment via api") == 8
    assert risk_score_to_level(6) == "MEDIUM"
    assert compute_complexity("build a complete api", risk_score=2) == "high"
    assert evaluate_approval(2, "low", "SUPERVISED")["auto_approved"] is True
