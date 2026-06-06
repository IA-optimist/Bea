"""
JARVIS — Improvement Proposal Store
=======================================
Stores improvement proposals for review in the Jarvis app.

Proposals come from:
- Self-improvement engine detecting repeated failures
- Tool performance tracker detecting degraded tools
- Mission performance tracker detecting failing mission types
- Manual submission via API

Proposals are reviewed in the Jarvis app before execution.
This is the approval-aware layer for controlled self-improvement.

Zero external dependencies. Fail-open.
"""
from __future__ import annotations

import json
import structlog
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = structlog.get_logger("jarvis.improvement_proposals")


@dataclass
class ImprovementProposal:
    """A single improvement proposal."""
    proposal_type: str = ""       # tool_fix, agent_config, planning_rule, retry_policy, new_tool
    title: str = ""
    description: str = ""
    affected_components: list[str] = field(default_factory=list)
    estimated_benefit: str = ""
    risk_score: int = 5           # 1-10
    source: str = "auto"          # auto, manual, tool_tracker, mission_tracker
    status: str = "pending"       # pending, approved, rejected, executed, failed
    proposal_id: str = ""
    created_at: float = 0.0
    reviewed_at: float = 0.0
    reviewer_note: str = ""
    execution_result: str = ""

    def __post_init__(self):
        if not self.proposal_id:
            self.proposal_id = f"prop-{uuid.uuid4().hex[:8]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class ProposalStore:
    """
    Stores improvement proposals on disk.

    Bounded: 500 proposals max. Oldest resolved proposals evicted.
    Persists to workspace/improvement_proposals.json.
    """

    MAX_PROPOSALS = 500
    PERSIST_FILE = "workspace/improvement_proposals.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._proposals: dict[str, ImprovementProposal] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def add(self, proposal: ImprovementProposal) -> str:
        """Add a proposal. Returns proposal_id."""
        self._ensure_loaded()

        # Evict oldest if at capacity (prefer evicting resolved first)
        if len(self._proposals) >= self.MAX_PROPOSALS:
            resolved = sorted(
                [p for p in self._proposals.values() if p.status != "pending"],
                key=lambda p: p.created_at,
            )
            if resolved:
                del self._proposals[resolved[0].proposal_id]
            else:
                # All pending — evict oldest pending
                oldest = min(self._proposals.values(), key=lambda p: p.created_at)
                del self._proposals[oldest.proposal_id]

        self._proposals[proposal.proposal_id] = proposal
        self.save()
        logger.info(
            "improvement_proposal_added",
            id=proposal.proposal_id,
            type=proposal.proposal_type,
            title=proposal.title[:60],
        )
        return proposal.proposal_id

    def approve(self, proposal_id: str) -> bool:
        """Approve a pending proposal."""
        self._ensure_loaded()
        p = self._proposals.get(proposal_id)
        if not p or p.status != "pending":
            return False
        p.status = "approved"
        p.reviewed_at = time.time()
        self.save()
        logger.info("improvement_proposal_approved", id=proposal_id)
        return True

    def reject(self, proposal_id: str, reason: str = "") -> bool:
        """Reject a pending proposal."""
        self._ensure_loaded()
        p = self._proposals.get(proposal_id)
        if not p or p.status != "pending":
            return False
        p.status = "rejected"
        p.reviewed_at = time.time()
        p.reviewer_note = reason[:500]
        self.save()
        logger.info("improvement_proposal_rejected", id=proposal_id, reason=reason[:60])
        return True

    def mark_executed(self, proposal_id: str, result: str = "") -> bool:
        """Mark an approved proposal as executed."""
        self._ensure_loaded()
        p = self._proposals.get(proposal_id)
        if not p or p.status != "approved":
            return False
        p.status = "executed"
        p.execution_result = result[:5000]
        self.save()
        return True

    def list_pending(self) -> list[dict]:
        self._ensure_loaded()
        return sorted(
            [p.to_dict() for p in self._proposals.values() if p.status == "pending"],
            key=lambda x: _priority_score(x),
            reverse=True,
        )

    def list_approved(self) -> list[dict]:
        self._ensure_loaded()
        return [p.to_dict() for p in self._proposals.values() if p.status == "approved"]

    def list_rejected(self) -> list[dict]:
        self._ensure_loaded()
        return [p.to_dict() for p in self._proposals.values() if p.status == "rejected"]

    def list_all(self) -> list[dict]:
        self._ensure_loaded()
        return sorted(
            [p.to_dict() for p in self._proposals.values()],
            key=lambda x: x["created_at"],
            reverse=True,
        )

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump(
                    [p.to_dict() for p in self._proposals.values()],
                    f, indent=2,
                )
            return True
        except Exception as e:
            logger.warning("proposal_save_failed: %s", str(e)[:80])
            return False

    def load(self) -> bool:
        if not os.path.exists(self._persist_path):
            return False
        try:
            with open(self._persist_path) as f:
                items = json.load(f)
            self._proposals.clear()
            for item in items:
                p = ImprovementProposal(**{
                    k: v for k, v in item.items()
                    if k in ImprovementProposal.__dataclass_fields__
                })
                self._proposals[p.proposal_id] = p
            return True
        except Exception as e:
            logger.warning("proposal_load_failed: %s", str(e)[:80])
            return False


def _priority_score(proposal: dict) -> float:
    """
    Score proposals for priority ranking. Higher = more important.
    Factors: type weight, inverse risk, recency.
    """
    import time
    TYPE_WEIGHTS = {
        "tool_fix": 10, "tool_optimization": 8,
        "routing_optimization": 7, "planning_rule": 6,
        "retry_policy": 5, "agent_config": 4, "new_tool": 3,
    }
    type_w = TYPE_WEIGHTS.get(proposal.get("proposal_type", ""), 2)
    risk = max(1, min(10, proposal.get("risk_score", 5)))
    risk_w = 11 - risk
    age_s = time.time() - proposal.get("created_at", 0)
    recency_w = max(0.5, min(2.0, 1.0 - age_s / 86400))
    return type_w * risk_w * recency_w


_store: Optional[ProposalStore] = None


def get_proposal_store() -> ProposalStore:
    global _store
    if _store is None:
        _store = ProposalStore()
    return _store
