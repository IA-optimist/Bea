"""
core/autonomy/multi_choice.py — Multi-choice human-in-the-loop decisions.

The existing core.approval_queue is binary : approve or reject. For
real autonomy collaboration, the daemon needs to surface :

    "I'm working on goal X. Here are 3 strategies. Which do you prefer ?"

and wait for the operator's pick. This module adds that primitive on
top of (not replacing) the existing ApprovalQueue ; the binary path
still works for legacy code.

A multi-choice decision is :
- An open question with 2-N choices
- Each choice has a label, description, optional metadata (cost, risk)
- A timeout — if no answer arrives, default to a chosen index or fail
- Backed by an in-memory store ; persisted to disk best-effort to
  survive restarts (workspace/multi_choice_decisions.json)

Two consumer flows :

A. Synchronous (blocking) — for tests / CLI :
    decision = ask("rotate_secrets_strategy", "Which approach?",
                   choices=[...], timeout_s=300, default_choice=0)
    # blocks up to timeout_s, returns the selected Choice

B. Async (event-driven) — for the autonomy daemon :
    pending = create("rotate_secrets_strategy", ...)
    # daemon continues other work
    # when operator answers via API → bus event "decision.answered"
    # daemon rebuilds context and resumes

The API surface is intentionally tiny ; full UX (mobile push, slack
embed) lives in api/routes/decisions.py (separate file, can come later).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from core.autonomy.event_bus import get_event_bus

log = structlog.get_logger(__name__)


@dataclass
class Choice:
    """A single answer option for the operator."""
    index: int
    label: str
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    """A pending or resolved multi-choice question."""
    decision_id: str
    name: str
    question: str
    choices: List[Choice]
    timeout_s: float = 0.0  # 0 = no timeout
    default_choice: int = -1  # -1 = no default, raise on timeout
    created_at: float = field(default_factory=time.time)
    answered_at: Optional[float] = None
    answered_by: str = ""
    selected_index: Optional[int] = None
    status: str = "pending"  # pending | answered | timeout | cancelled
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status in ("answered", "timeout", "cancelled")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["choices"] = [c.to_dict() for c in self.choices]
        return d


# ── Store ────────────────────────────────────────────────────
_STORE_PATH = Path(os.environ.get(
    "BEA_MULTI_CHOICE_STORE",
    "workspace/multi_choice_decisions.json",
))


class MultiChoiceStore:
    """Singleton in-memory store with best-effort JSON persistence."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _STORE_PATH
        self._decisions: Dict[str, Decision] = {}
        self._cv = threading.Condition()
        self._load()

    # ── Persistence (fail-open) ───────────────────────────────
    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for item in raw:
                    choices = [Choice(**c) for c in item.pop("choices", [])]
                    d = Decision(**item, choices=choices)
                    self._decisions[d.decision_id] = d
        except Exception as exc:
            log.debug("multi_choice.load_failed", err=str(exc)[:80])

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with self._cv:
                data = [d.to_dict() for d in self._decisions.values()]
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as exc:
            log.debug("multi_choice.save_failed", err=str(exc)[:80])

    # ── CRUD ──────────────────────────────────────────────────
    def create(
        self,
        name: str,
        question: str,
        choices: List[Choice],
        timeout_s: float = 0.0,
        default_choice: int = -1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Decision:
        if not choices:
            raise ValueError("choices must be non-empty")
        # Reindex defensively
        choices = [
            Choice(index=i, label=c.label, description=c.description, metadata=c.metadata)
            for i, c in enumerate(choices)
        ]
        d = Decision(
            decision_id=str(uuid.uuid4()),
            name=name,
            question=question,
            choices=choices,
            timeout_s=timeout_s,
            default_choice=default_choice,
            metadata=dict(metadata or {}),
        )
        with self._cv:
            self._decisions[d.decision_id] = d
            self._cv.notify_all()
        self._save()
        get_event_bus().publish("decision.created", {
            "decision_id": d.decision_id,
            "name": name,
            "question": question[:200],
            "choice_count": len(choices),
            "timeout_s": timeout_s,
        })
        return d

    def get(self, decision_id: str) -> Optional[Decision]:
        with self._cv:
            return self._decisions.get(decision_id)

    def pending(self) -> List[Decision]:
        with self._cv:
            return [d for d in self._decisions.values() if d.status == "pending"]

    def answer(
        self,
        decision_id: str,
        selected_index: int,
        answered_by: str = "human",
    ) -> Optional[Decision]:
        with self._cv:
            d = self._decisions.get(decision_id)
            if d is None or d.is_resolved:
                return None
            if not (0 <= selected_index < len(d.choices)):
                raise ValueError(f"selected_index {selected_index} out of range")
            d.status = "answered"
            d.selected_index = selected_index
            d.answered_at = time.time()
            d.answered_by = answered_by
            self._cv.notify_all()
        self._save()
        get_event_bus().publish("decision.answered", {
            "decision_id": decision_id,
            "name": d.name,
            "selected_index": selected_index,
            "answered_by": answered_by,
        })
        return d

    def cancel(self, decision_id: str, reason: str = "") -> bool:
        with self._cv:
            d = self._decisions.get(decision_id)
            if d is None or d.is_resolved:
                return False
            d.status = "cancelled"
            d.metadata["cancel_reason"] = reason
            d.answered_at = time.time()
            self._cv.notify_all()
        self._save()
        get_event_bus().publish("decision.cancelled", {
            "decision_id": decision_id,
            "reason": reason,
        })
        return True

    # ── Blocking await ────────────────────────────────────────
    def wait(self, decision_id: str, max_wait_s: Optional[float] = None) -> Decision:
        """Block until the decision is resolved (answer/timeout/cancel).

        Returns the resolved Decision. If `max_wait_s` is set and the
        decision is still pending, applies the configured timeout
        behavior :
          - default_choice >= 0  → auto-select that index, mark `timeout`
          - default_choice < 0   → raise TimeoutError
        """
        deadline_relative = max_wait_s
        with self._cv:
            d = self._decisions.get(decision_id)
            if d is None:
                raise KeyError(f"unknown decision_id: {decision_id}")

            # Honor configured timeout if no caller-side override
            wait_budget = deadline_relative if deadline_relative is not None else (
                d.timeout_s if d.timeout_s > 0 else None
            )

            start = time.time()
            while not d.is_resolved:
                remaining = None
                if wait_budget is not None:
                    remaining = wait_budget - (time.time() - start)
                    if remaining <= 0:
                        # Apply timeout policy
                        if d.default_choice >= 0:
                            d.status = "timeout"
                            d.selected_index = d.default_choice
                            d.answered_at = time.time()
                            d.answered_by = "system:timeout"
                            self._cv.notify_all()
                            self._save()
                            get_event_bus().publish("decision.timed_out", {
                                "decision_id": decision_id,
                                "default_choice": d.default_choice,
                            })
                            return d
                        else:
                            raise TimeoutError(f"decision {decision_id} timed out")
                self._cv.wait(timeout=remaining)
            return d


# ── Singleton ────────────────────────────────────────────────
_STORE: Optional[MultiChoiceStore] = None
_STORE_LOCK = threading.Lock()


def get_multi_choice_store() -> MultiChoiceStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = MultiChoiceStore()
    return _STORE


def reset_multi_choice_store() -> None:
    """Test fixture hook."""
    global _STORE
    with _STORE_LOCK:
        _STORE = None


def ask(
    name: str,
    question: str,
    choices: List[Choice],
    timeout_s: float = 0.0,
    default_choice: int = -1,
    blocking: bool = True,
) -> Decision:
    """Convenience helper : create a decision and (optionally) block on it."""
    store = get_multi_choice_store()
    decision = store.create(name, question, choices, timeout_s, default_choice)
    if not blocking:
        return decision
    return store.wait(decision.decision_id)
