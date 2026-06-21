"""core/evaluation/ingestion.py — Programmatic API for ingesting mission reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.evaluation.mission_learning import MissionLearner
from core.evaluation.mission_report_parser import MissionReportParser
from core.memory.operational_memory import OperationalMemoryStore


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".markdown"}:
            files.append(path)
    return sorted(files)


def ingest(
    path: str | Path,
    store: OperationalMemoryStore | None = None,
) -> dict[str, Any]:
    """Ingest a single mission report or a directory of reports into memory."""
    root = Path(path)
    files = _collect_files(root)
    if not files:
        return {
            "reports_read": 0,
            "memories_created": 0,
            "memories_updated": 0,
            "warnings": [f"No reports found at {root}"],
            "errors": [],
            "details": [],
        }

    parser = MissionReportParser()
    learner = MissionLearner(store=store)

    total_created = 0
    total_updated = 0
    all_warnings: list[str] = []
    all_errors: list[str] = []
    details: list[dict[str, Any]] = []

    for file_path in files:
        try:
            inp = parser.parse_file(file_path)
            result = learner.learn(inp)
            total_created += len(result.created_memory_ids)
            total_updated += len(result.updated_memory_ids)
            all_warnings.extend(result.warnings)
            all_errors.extend(result.errors)
            details.append({
                "file": str(file_path),
                "mission_id": inp.mission_id,
                "created": len(result.created_memory_ids),
                "updated": len(result.updated_memory_ids),
            })
        except Exception as exc:
            all_errors.append(f"{file_path}: {exc}")

    return {
        "reports_read": len(files),
        "memories_created": total_created,
        "memories_updated": total_updated,
        "warnings": all_warnings,
        "errors": all_errors,
        "details": details,
    }


def ingest_json(path: str | Path, store: OperationalMemoryStore | None = None) -> str:
    """Ingest reports and return a JSON summary string."""
    return json.dumps(ingest(path, store=store), indent=2, ensure_ascii=False)
