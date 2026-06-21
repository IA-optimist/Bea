"""Evaluation helpers: model routing, mission learning, and memory selection."""
from core.evaluation.ingestion import ingest
from core.evaluation.mission_learning import MissionLearner, learn_from_mission_report
from core.evaluation.mission_report_parser import MissionLearningInput, MissionReportParser
from core.evaluation.model_router import ModelClass, ModelRouter

__all__ = [
    "ModelClass",
    "ModelRouter",
    "MissionReportParser",
    "MissionLearningInput",
    "MissionLearner",
    "learn_from_mission_report",
    "ingest",
]
