"""Failure memory for the Bea coding agent.

Records failures and successes from coding tasks so that future similar issues
can reuse the winning strategy. Persistence is a local JSON file by default;
the module has no heavyweight dependencies and can be swapped for a vector store
later without changing the public interface.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable


_STOPWORDS = frozenset({"the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are", "be"})


def _tokens(text: str) -> frozenset[str]:
    """Return lower-cased alphanumeric tokens, excluding common stopwords."""
    return frozenset(
        token for token in re.findall(r"[a-z0-9_]+", text.lower())
        if token not in _STOPWORDS and len(token) > 1
    )


@dataclass(frozen=True)
class FailureRecord:
    """One entry in the failure memory.

    Attributes:
        issue: short description of the issue (e.g. GitHub title).
        cause: root cause as diagnosed by the agent.
        files_touched: files that were changed to fix the issue.
        error_text: relevant error/traceback text.
        successful_correction: the patch / command / strategy that fixed it.
        outcome: "success" if the correction worked, "failure" otherwise.
        timestamp: Unix timestamp of the record.
        tags: optional tags for grouping/filtering.
    """

    issue: str
    cause: str
    files_touched: tuple[str, ...]
    error_text: str
    successful_correction: str
    outcome: str = "success"
    timestamp: float = field(default_factory=time.time)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome not in {"success", "failure"}:
            raise ValueError(f"outcome must be 'success' or 'failure', got {self.outcome!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FailureRecord":
        return cls(**data)


class FailureMemory:
    """Store and query failure/success records for coding-agent missions.

    Example:
        memory = FailureMemory(Path("workspace/coding_agent/failure_memory.json"))
        memory.add(FailureRecord(
            issue="shell=True in gateway/local_tools.py",
            cause="subprocess called with shell=True",
            files_touched=("gateway/local_tools.py",),
            error_text="security linter blocked shell=True",
            successful_correction="replace shell=True with shlex.split and subprocess.run",
            outcome="success",
        ))
        suggestions = memory.search("unsafe subprocess shell execution")
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else Path("workspace/coding_agent/failure_memory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: tuple[FailureRecord, ...] = ()
        self._load()

    def add(self, record: FailureRecord) -> None:
        """Append a record and persist."""
        self._records = self._records + (record,)
        self._save()

    def record_failure(
        self,
        issue: str,
        cause: str,
        files_touched: Iterable[str],
        error_text: str,
        tags: Iterable[str] = (),
    ) -> FailureRecord:
        """Convenience helper to record a failure."""
        record = FailureRecord(
            issue=issue,
            cause=cause,
            files_touched=tuple(files_touched),
            error_text=error_text,
            successful_correction="",
            outcome="failure",
            tags=tuple(tags),
        )
        self.add(record)
        return record

    def record_success(
        self,
        issue: str,
        cause: str,
        files_touched: Iterable[str],
        error_text: str,
        successful_correction: str,
        tags: Iterable[str] = (),
    ) -> FailureRecord:
        """Convenience helper to record a successful fix."""
        record = FailureRecord(
            issue=issue,
            cause=cause,
            files_touched=tuple(files_touched),
            error_text=error_text,
            successful_correction=successful_correction,
            outcome="success",
            tags=tuple(tags),
        )
        self.add(record)
        return record

    def search(self, issue: str, top_k: int = 5) -> list[tuple[float, FailureRecord]]:
        """Return the most relevant records for ``issue``.

        The ranking is token-based today; enough to prove the concept. A vector
        backend can be plugged in later.
        """
        query_tokens = _tokens(issue)
        if not query_tokens:
            return [(1.0, rec) for rec in self._records[-top_k:]]

        scored: list[tuple[float, FailureRecord]] = []
        for rec in self._records:
            score = self._score(rec, query_tokens)
            if score > 0:
                scored.append((score, rec))
        scored.sort(key=lambda item: (item[0], item[1].timestamp), reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._records)

    def _score(self, rec: FailureRecord, query: frozenset[str]) -> float:
        text = " ".join([rec.issue, rec.cause, rec.error_text, rec.successful_correction])
        file_text = " ".join(rec.files_touched)
        text_tokens = _tokens(text)
        file_tokens = _tokens(file_text)
        tags_tokens = _tokens(" ".join(rec.tags))

        score = 0.0
        overlap_text = len(query & text_tokens)
        overlap_files = len(query & file_tokens)
        overlap_tags = len(query & tags_tokens)
        score += overlap_text * 1.0
        score += overlap_files * 2.0  # matching a file path is strong signal
        score += overlap_tags * 1.5
        if rec.outcome == "success":
            score *= 1.2  # prefer winning strategies
        return score

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._records = tuple(FailureRecord.from_dict(item) for item in raw)
        except (OSError, json.JSONDecodeError, TypeError):
            self._records = ()

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = [rec.to_dict() for rec in self._records]
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
