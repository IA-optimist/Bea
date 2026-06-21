"""
core/evaluation/mission_report_parser.py — Parse mission reports into a normalized input.

Supports:
    - JSON reports (snake_case or camelCase keys)
    - Minimal Markdown reports (fallback when JSON is unavailable)

Never crashes on missing fields: every field has a safe default.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MissionLearningInput:
    """Normalized mission report input for the learning loop."""

    mission_id: str = ""
    title: str = ""
    status: str = ""
    task_type: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    success: bool = False
    failure_reason: str = ""
    model_used: str = ""
    model_class: str = ""
    duration_ms: int = 0
    cost_estimate: float | None = None
    lessons_learned: str = ""
    risks_detected: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "title": self.title,
            "status": self.status,
            "task_type": self.task_type,
            "files_changed": self.files_changed,
            "tests_run": self.tests_run,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "model_used": self.model_used,
            "model_class": self.model_class,
            "duration_ms": self.duration_ms,
            "cost_estimate": self.cost_estimate,
            "lessons_learned": self.lessons_learned,
            "risks_detected": self.risks_detected,
            "created_at": self.created_at,
        }


class MissionReportParser:
    """Robust parser for mission reports."""

    def parse(self, raw: str | Path | dict[str, Any]) -> MissionLearningInput:
        """Parse a report from a Path, JSON string, or dict."""
        if isinstance(raw, dict):
            return self._from_dict(raw)
        if isinstance(raw, Path):
            raw = raw.read_text(encoding="utf-8")
        text = raw.strip()
        if text.startswith("{"):
            return self._from_json(text)
        return self._from_markdown(text)

    def parse_file(self, path: str | Path) -> MissionLearningInput:
        return self.parse(Path(path))

    def _from_json(self, text: str) -> MissionLearningInput:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            inp = MissionLearningInput()
            inp.warnings.append(f"Invalid JSON: {exc}")
            return inp
        return self._from_dict(data)

    def _from_dict(self, data: dict[str, Any]) -> MissionLearningInput:
        data = {self._normalize_key(k): v for k, v in data.items()}
        inp = MissionLearningInput()
        inp.mission_id = self._str(data, "mission_id", "missionId", "id")
        inp.title = self._str(data, "title", "name")
        inp.status = self._str(data, "status", "state")
        inp.task_type = self._str(data, "task_type", "taskType", "type")
        inp.files_changed = self._list(data, "files_changed", "filesChanged", "files")
        inp.tests_run = self._list(data, "tests_run", "testsRun", "tests")
        inp.success = self._bool(data, "success", "ok")
        inp.failure_reason = self._str(data, "failure_reason", "failureReason", "error", "message")
        inp.model_used = self._str(data, "model_used", "modelUsed", "model")
        inp.model_class = self._str(data, "model_class", "modelClass")
        inp.duration_ms = self._int(data, "duration_ms", "durationMs", "duration")
        inp.cost_estimate = self._float_or_none(data, "cost_estimate", "costEstimate", "cost")
        inp.lessons_learned = self._str(data, "lessons_learned", "lessonsLearned", "lessons")
        inp.risks_detected = self._list(data, "risks_detected", "risksDetected", "risks")
        inp.created_at = self._float(data, "created_at", "createdAt", default=time.time())

        # Derive success from status if not explicit
        if "success" not in data and "ok" not in data and inp.status:
            status_lower = inp.status.lower()
            if status_lower in {"success", "completed", "done"}:
                inp.success = True
            elif status_lower in {"failure", "failed", "error", "needs_fix"}:
                inp.success = False

        if not inp.mission_id:
            inp.warnings.append("Missing mission_id; using empty string")
        if not inp.task_type:
            inp.warnings.append("Missing task_type; using empty string")
        return inp

    def _from_markdown(self, text: str) -> MissionLearningInput:
        inp = MissionLearningInput()
        inp.title = self._md_field(text, "title", "mission", "mission title") or ""
        inp.status = self._md_field(text, "status", "state") or ""
        inp.task_type = self._md_field(text, "task type", "type") or ""
        inp.model_used = self._md_field(text, "model", "model used") or ""
        inp.model_class = self._md_field(text, "model class", "model_class") or ""
        inp.failure_reason = self._md_field(text, "failure reason", "error") or ""
        inp.lessons_learned = self._md_field(text, "lessons learned", "learnings") or ""
        inp.duration_ms = self._int_from_md(text, "duration")
        inp.files_changed = self._md_list(text, "files changed", "files")
        inp.tests_run = self._md_list(text, "tests run", "tests")
        inp.risks_detected = self._md_list(text, "risks", "risks detected")

        if inp.status.lower() in {"success", "completed", "done"}:
            inp.success = True
        elif inp.status.lower() in {"failure", "failed", "error", "needs_fix"}:
            inp.success = False

        if not inp.title:
            inp.warnings.append("Markdown parsing produced no title")
        return inp

    @staticmethod
    def _normalize_key(key: str) -> str:
        # camelCase to snake_case
        s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower().replace("-", "_")

    def _str(self, data: dict[str, Any], *keys: str) -> str:
        for k in keys:
            if k in data and data[k] is not None:
                return str(data[k])
        return ""

    def _list(self, data: dict[str, Any], *keys: str) -> list[str]:
        for k in keys:
            if k in data and data[k] is not None:
                value = data[k]
                if isinstance(value, str):
                    return [item.strip() for item in value.split(",") if item.strip()]
                if isinstance(value, list):
                    return [str(item) for item in value if item is not None]
        return []

    def _bool(self, data: dict[str, Any], *keys: str) -> bool:
        for k in keys:
            if k in data and data[k] is not None:
                v = data[k]
                if isinstance(v, bool):
                    return v
                return str(v).lower() in {"true", "1", "yes", "success"}
        return False

    def _int(self, data: dict[str, Any], *keys: str) -> int:
        for k in keys:
            if k in data and data[k] is not None:
                try:
                    return int(data[k])
                except (ValueError, TypeError):
                    pass
        return 0

    def _float_or_none(self, data: dict[str, Any], *keys: str) -> float | None:
        for k in keys:
            if k in data and data[k] is not None:
                try:
                    return float(data[k])
                except (ValueError, TypeError):
                    pass
        return None

    def _float(self, data: dict[str, Any], *keys: str, default: float = 0.0) -> float:
        for k in keys:
            if k in data and data[k] is not None:
                try:
                    return float(data[k])
                except (ValueError, TypeError):
                    pass
        return default

    def _md_field(self, text: str, *labels: str) -> str | None:
        for label in labels:
            pattern = re.compile(
                rf"[\n\r#\-]*\s*{re.escape(label)}\s*:?\s*(.+?)(?:\n\n|\r?\n\s*[-*#]|\Z)",
                re.IGNORECASE | re.DOTALL,
            )
            match = pattern.search(text)
            if match:
                value = match.group(1).strip()
                # Stop at next section label on its own line
                value = re.split(r"\r?\n\s*[A-Za-z ]+\s*:", value)[0].strip()
                return value
        return None

    def _int_from_md(self, text: str, label: str) -> int:
        field = self._md_field(text, label)
        if field:
            numbers = re.findall(r"\d+", field)
            if numbers:
                return int(numbers[0])
        return 0

    def _md_list(self, text: str, *labels: str) -> list[str]:
        for label in labels:
            pattern = re.compile(
                rf"[\n\r#\-]*\s*{re.escape(label)}\s*:?\s*\n?(.*?)(?:\n\n|\n#|\Z)",
                re.IGNORECASE | re.DOTALL,
            )
            match = pattern.search(text)
            if match:
                block = match.group(1)
                items = re.findall(r"[-*]\s*(.+)", block)
                if items:
                    return [item.strip() for item in items if item.strip()]
                # Comma-separated fallback
                return [item.strip() for item in block.split(",") if item.strip()]
        return []
