"""
BEA — Business Pipeline Manager
======================================
Lightweight CRM + pipeline tracker for digital micro-business operations.

This is a STRUCTURED DATA LAYER, not an orchestrator.
It stores and queries pipeline state; the planner and mission system
decide what actions to take.

Capabilities:
1. Lead/Prospect tracking (bounded)
2. Pipeline stages (lead → qualified → proposal → active → delivered → closed)
3. Content pipeline (idea → draft → review → published)
4. Budget/cost tracking per objective
5. Revenue pipeline signals (expected value, conversion rate)
6. Pipeline health signals for cockpit

Integrates with:
  - json_storage connector (persistence)
  - operating_primitives (economics, objectives)
  - workflow_runtime (can trigger workflows on stage changes)
  - connectors (document_writer for proposals, email for outreach)

Zero external dependencies. Fail-open everywhere.
Bounded: 200 leads, 100 content items, 500 budget entries.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger("bea.business_pipeline")


# ═══════════════════════════════════════════════════════════════
# 1. LEAD / PROSPECT TRACKER
# ═══════════════════════════════════════════════════════════════

LEAD_STAGES = ["lead", "qualified", "proposal_sent", "negotiation", "active", "delivered", "closed", "lost"]
MAX_LEADS = 200


@dataclass
class Lead:
    """A prospect / lead / client in the pipeline."""
    lead_id: str = ""
    name: str = ""
    source: str = ""               # where this lead came from
    stage: str = "lead"            # current pipeline stage
    value_estimate: float = 0.0    # estimated deal value
    notes: str = ""
    tags: list = field(default_factory=list)
    contact_info: dict = field(default_factory=dict)  # email, platform, handle
    created_at: float = 0.0
    updated_at: float = 0.0
    stage_history: list = field(default_factory=list)  # [{stage, timestamp}]
    interactions: int = 0
    next_action: str = ""          # what to do next
    objective_id: str = ""         # linked objective (optional)

    def to_dict(self) -> dict:
        return asdict(self)

    def advance(self, new_stage: str, note: str = "") -> bool:
        """Move lead to next pipeline stage."""
        if new_stage not in LEAD_STAGES:
            return False
        self.stage_history.append({
            "from": self.stage, "to": new_stage,
            "timestamp": time.time(), "note": note[:200],
        })
        self.stage = new_stage
        self.updated_at = time.time()
        return True


class LeadTracker:
    """Tracks leads through the business pipeline."""
    PERSIST_FILE = "workspace/leads.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._leads: dict[str, Lead] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def add_lead(self, name: str, source: str = "", value_estimate: float = 0.0,
                 tags: list = None, contact_info: dict = None,
                 notes: str = "", objective_id: str = "") -> Lead:
        """Add a new lead to the pipeline."""
        self._ensure_loaded()
        if len(self._leads) >= MAX_LEADS:
            # Evict oldest closed/lost lead
            closed = [l for l in self._leads.values() if l.stage in ("closed", "lost")]
            if closed:
                oldest = min(closed, key=lambda l: l.updated_at)
                del self._leads[oldest.lead_id]
            else:
                raise ValueError(f"Lead limit reached ({MAX_LEADS})")

        lead = Lead(
            lead_id=str(uuid.uuid4())[:8],
            name=name[:200],
            source=source[:100],
            value_estimate=value_estimate,
            tags=(tags or [])[:10],
            contact_info=contact_info or {},
            notes=notes[:500],
            objective_id=objective_id,
            created_at=time.time(),
            updated_at=time.time(),
            stage_history=[{"from": "", "to": "lead", "timestamp": time.time()}],
        )
        self._leads[lead.lead_id] = lead
        self.save()
        return lead

    def advance_lead(self, lead_id: str, new_stage: str, note: str = "") -> Optional[Lead]:
        """Move a lead to the next stage."""
        self._ensure_loaded()
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        if not lead.advance(new_stage, note):
            return None
        self.save()
        return lead

    def update_lead(self, lead_id: str, **kwargs) -> Optional[Lead]:
        """Update lead fields."""
        self._ensure_loaded()
        lead = self._leads.get(lead_id)
        if not lead:
            return None
        for k, v in kwargs.items():
            if hasattr(lead, k) and k not in ("lead_id", "created_at", "stage_history"):
                setattr(lead, k, v)
        lead.updated_at = time.time()
        self.save()
        return lead

    def get_lead(self, lead_id: str) -> Optional[Lead]:
        self._ensure_loaded()
        return self._leads.get(lead_id)

    def list_leads(self, stage: str = "", tag: str = "") -> list[dict]:
        """List leads with optional filtering."""
        self._ensure_loaded()
        leads = list(self._leads.values())
        if stage:
            leads = [l for l in leads if l.stage == stage]
        if tag:
            leads = [l for l in leads if tag in l.tags]
        return [l.to_dict() for l in sorted(leads, key=lambda l: l.updated_at, reverse=True)[:50]]

    def get_pipeline_summary(self) -> dict:
        """Pipeline health signals."""
        self._ensure_loaded()
        by_stage = {}
        for stage in LEAD_STAGES:
            stage_leads = [l for l in self._leads.values() if l.stage == stage]
            by_stage[stage] = {
                "count": len(stage_leads),
                "total_value": round(sum(l.value_estimate for l in stage_leads), 2),
            }

        total = len(self._leads)
        active = sum(1 for l in self._leads.values()
                     if l.stage not in ("closed", "lost"))
        won = sum(1 for l in self._leads.values() if l.stage in ("delivered", "closed"))
        lost = sum(1 for l in self._leads.values() if l.stage == "lost")
        conversion = won / max(won + lost, 1)

        # Pipeline velocity: avg time from lead to active
        velocities = []
        for lead in self._leads.values():
            if lead.stage in ("active", "delivered", "closed"):
                first = lead.stage_history[0]["timestamp"] if lead.stage_history else lead.created_at
                last = lead.updated_at
                velocities.append(last - first)
        avg_velocity_days = (sum(velocities) / len(velocities) / 86400) if velocities else 0

        total_pipeline_value = sum(
            l.value_estimate for l in self._leads.values()
            if l.stage not in ("closed", "lost")
        )

        return {
            "total_leads": total,
            "active_leads": active,
            "by_stage": by_stage,
            "conversion_rate": round(conversion, 3),
            "avg_velocity_days": round(avg_velocity_days, 1),
            "total_pipeline_value": round(total_pipeline_value, 2),
            "won": won,
            "lost": lost,
        }

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._leads.items()}, f, indent=2)
        except Exception as e:
            logger.warning("leads_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for lid, d in data.items():
                self._leads[lid] = Lead(
                    **{k: v for k, v in d.items() if k in Lead.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("leads_load_failed: %s", str(e)[:80])


# ═══════════════════════════════════════════════════════════════
# 2. CONTENT PIPELINE
# ═══════════════════════════════════════════════════════════════

CONTENT_STAGES = ["idea", "research", "draft", "review", "revision", "published", "archived"]
MAX_CONTENT_ITEMS = 100


@dataclass
class ContentItem:
    """A content item in the pipeline (blog post, doc, proposal, etc.)."""
    content_id: str = ""
    title: str = ""
    content_type: str = "article"   # article, proposal, report, social, documentation
    stage: str = "idea"
    body: str = ""                  # actual content (bounded)
    tags: list = field(default_factory=list)
    target_audience: str = ""
    lead_id: str = ""               # linked lead (if proposal)
    objective_id: str = ""          # linked objective
    created_at: float = 0.0
    updated_at: float = 0.0
    stage_history: list = field(default_factory=list)
    word_count: int = 0
    quality_score: float = 0.0      # 0-1 if evaluated

    def to_dict(self) -> dict:
        d = asdict(self)
        d["body"] = d["body"][:500] + "..." if len(d["body"]) > 500 else d["body"]
        return d

    def advance(self, new_stage: str) -> bool:
        if new_stage not in CONTENT_STAGES:
            return False
        self.stage_history.append({
            "from": self.stage, "to": new_stage, "timestamp": time.time(),
        })
        self.stage = new_stage
        self.updated_at = time.time()
        return True


class ContentPipeline:
    """Manages content creation pipeline."""
    PERSIST_FILE = "workspace/content_pipeline.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._items: dict[str, ContentItem] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def create(self, title: str, content_type: str = "article",
               body: str = "", tags: list = None,
               lead_id: str = "", objective_id: str = "") -> ContentItem:
        """Create a new content item."""
        self._ensure_loaded()
        if len(self._items) >= MAX_CONTENT_ITEMS:
            archived = [c for c in self._items.values() if c.stage == "archived"]
            if archived:
                oldest = min(archived, key=lambda c: c.updated_at)
                del self._items[oldest.content_id]
            else:
                raise ValueError(f"Content limit reached ({MAX_CONTENT_ITEMS})")

        item = ContentItem(
            content_id=str(uuid.uuid4())[:8],
            title=title[:200],
            content_type=content_type,
            body=body[:50_000],
            tags=(tags or [])[:10],
            lead_id=lead_id,
            objective_id=objective_id,
            created_at=time.time(),
            updated_at=time.time(),
            word_count=len(body.split()),
            stage_history=[{"from": "", "to": "idea", "timestamp": time.time()}],
        )
        self._items[item.content_id] = item
        self.save()
        return item

    def advance(self, content_id: str, new_stage: str) -> Optional[ContentItem]:
        self._ensure_loaded()
        item = self._items.get(content_id)
        if not item:
            return None
        if not item.advance(new_stage):
            return None
        self.save()
        return item

    def update_body(self, content_id: str, body: str) -> Optional[ContentItem]:
        self._ensure_loaded()
        item = self._items.get(content_id)
        if not item:
            return None
        item.body = body[:50_000]
        item.word_count = len(body.split())
        item.updated_at = time.time()
        self.save()
        return item

    def get(self, content_id: str) -> Optional[ContentItem]:
        self._ensure_loaded()
        return self._items.get(content_id)

    def list_items(self, stage: str = "", content_type: str = "") -> list[dict]:
        self._ensure_loaded()
        items = list(self._items.values())
        if stage:
            items = [i for i in items if i.stage == stage]
        if content_type:
            items = [i for i in items if i.content_type == content_type]
        return [i.to_dict() for i in sorted(items, key=lambda i: i.updated_at, reverse=True)[:50]]

    def get_summary(self) -> dict:
        self._ensure_loaded()
        by_stage = {}
        for stage in CONTENT_STAGES:
            by_stage[stage] = sum(1 for i in self._items.values() if i.stage == stage)
        by_type = {}
        for item in self._items.values():
            by_type[item.content_type] = by_type.get(item.content_type, 0) + 1
        return {
            "total": len(self._items),
            "by_stage": by_stage,
            "by_type": by_type,
        }

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._items.items()}, f, indent=2)
        except Exception as e:
            logger.warning("content_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for cid, d in data.items():
                self._items[cid] = ContentItem(
                    **{k: v for k, v in d.items() if k in ContentItem.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("content_load_failed: %s", str(e)[:80])


# ═══════════════════════════════════════════════════════════════
# 3. BUDGET / COST TRACKER
# ═══════════════════════════════════════════════════════════════

MAX_BUDGET_ENTRIES = 500


@dataclass
class BudgetEntry:
    """A cost or revenue entry."""
    entry_id: str = ""
    category: str = ""            # tool_cost, api_cost, time_cost, revenue, refund
    amount: float = 0.0           # positive = revenue, negative = cost
    currency: str = "USD"
    description: str = ""
    objective_id: str = ""        # linked objective
    lead_id: str = ""             # linked lead
    mission_id: str = ""          # linked mission
    timestamp: float = 0.0
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class BudgetTracker:
    """Tracks costs and revenue with per-objective breakdown."""
    PERSIST_FILE = "workspace/budget.jsonl"

    def __init__(self, persist_path: Optional[str] = None):
        self._entries: list[BudgetEntry] = []
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def record(self, category: str, amount: float, description: str = "",
               objective_id: str = "", lead_id: str = "",
               mission_id: str = "", currency: str = "USD",
               tags: list = None) -> BudgetEntry:
        """Record a budget entry."""
        self._ensure_loaded()
        entry = BudgetEntry(
            entry_id=str(uuid.uuid4())[:8],
            category=category[:50],
            amount=round(amount, 2),
            currency=currency,
            description=description[:200],
            objective_id=objective_id,
            lead_id=lead_id,
            mission_id=mission_id,
            timestamp=time.time(),
            tags=(tags or [])[:5],
        )
        self._entries.append(entry)
        if len(self._entries) > MAX_BUDGET_ENTRIES:
            self._entries = self._entries[-MAX_BUDGET_ENTRIES:]
        self.save()
        return entry

    def get_summary(self, objective_id: str = "", days: int = 30) -> dict:
        """Get budget summary with optional filtering."""
        self._ensure_loaded()
        cutoff = time.time() - (days * 86400)
        entries = [e for e in self._entries if e.timestamp >= cutoff]
        if objective_id:
            entries = [e for e in entries if e.objective_id == objective_id]

        total_revenue = sum(e.amount for e in entries if e.amount > 0)
        total_cost = sum(abs(e.amount) for e in entries if e.amount < 0)
        net = total_revenue - total_cost

        by_category = {}
        for e in entries:
            by_category.setdefault(e.category, 0)
            by_category[e.category] = round(by_category[e.category] + e.amount, 2)

        by_objective = {}
        for e in entries:
            if e.objective_id:
                by_objective.setdefault(e.objective_id, {"revenue": 0, "cost": 0})
                if e.amount > 0:
                    by_objective[e.objective_id]["revenue"] += e.amount
                else:
                    by_objective[e.objective_id]["cost"] += abs(e.amount)

        return {
            "period_days": days,
            "total_entries": len(entries),
            "total_revenue": round(total_revenue, 2),
            "total_cost": round(total_cost, 2),
            "net": round(net, 2),
            "roi": round(total_revenue / max(total_cost, 0.01), 2),
            "by_category": by_category,
            "by_objective": {k: {kk: round(vv, 2) for kk, vv in v.items()}
                            for k, v in by_objective.items()},
        }

    def list_entries(self, limit: int = 50) -> list[dict]:
        self._ensure_loaded()
        return [e.to_dict() for e in self._entries[-limit:]]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                for e in self._entries:
                    f.write(json.dumps(e.to_dict()) + "\n")
        except Exception as e:
            logger.warning("budget_save_failed: %s", str(e)[:80])

    def load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        self._entries.append(BudgetEntry(
                            **{k: v for k, v in d.items() if k in BudgetEntry.__dataclass_fields__}
                        ))
            if len(self._entries) > MAX_BUDGET_ENTRIES:
                self._entries = self._entries[-MAX_BUDGET_ENTRIES:]
        except Exception as e:
            logger.warning("budget_load_failed: %s", str(e)[:80])


# ═══════════════════════════════════════════════════════════════
# 4. UNIFIED BUSINESS DASHBOARD
# ═══════════════════════════════════════════════════════════════

def get_business_dashboard(leads: LeadTracker, content: ContentPipeline,
                           budget: BudgetTracker) -> dict:
    """Unified business intelligence dashboard."""
    pipeline = leads.get_pipeline_summary()
    content_summary = content.get_summary()
    budget_summary = budget.get_summary()

    # Health score: composite
    health_signals = []
    if pipeline["active_leads"] > 0:
        health_signals.append(0.3)  # has active pipeline
    if pipeline["conversion_rate"] > 0.2:
        health_signals.append(0.2)
    if content_summary["total"] > 0:
        health_signals.append(0.2)
    if budget_summary["net"] >= 0:
        health_signals.append(0.3)

    return {
        "pipeline": pipeline,
        "content": content_summary,
        "budget": budget_summary,
        "health_score": round(sum(health_signals), 2),
        "actions_needed": _detect_actions_needed(pipeline, content_summary, budget_summary),
    }


def _detect_actions_needed(pipeline: dict, content: dict, budget: dict) -> list[dict]:
    """Detect what actions should be taken next."""
    actions = []

    # No leads → need prospecting
    if pipeline["active_leads"] == 0:
        actions.append({
            "priority": "high",
            "action": "prospecting",
            "description": "No active leads — start prospecting for new opportunities",
        })

    # Leads stuck in early stages
    early = (pipeline["by_stage"].get("lead", {}).get("count", 0) +
             pipeline["by_stage"].get("qualified", {}).get("count", 0))
    if early > 5:
        actions.append({
            "priority": "medium",
            "action": "qualification",
            "description": f"{early} leads need qualification or outreach",
        })

    # Content stuck in draft
    drafts = content.get("by_stage", {}).get("draft", 0)
    if drafts > 3:
        actions.append({
            "priority": "medium",
            "action": "content_review",
            "description": f"{drafts} content items stuck in draft stage",
        })

    # Negative budget
    if budget["net"] < 0:
        actions.append({
            "priority": "high",
            "action": "cost_review",
            "description": f"Net budget is negative ({budget['net']})",
        })

    return actions


# ═══════════════════════════════════════════════════════════════
# SINGLETONS
# ═══════════════════════════════════════════════════════════════

_lead_tracker: Optional[LeadTracker] = None
_content_pipeline: Optional[ContentPipeline] = None
_budget_tracker: Optional[BudgetTracker] = None


def get_lead_tracker() -> LeadTracker:
    global _lead_tracker
    if _lead_tracker is None:
        _lead_tracker = LeadTracker()
    return _lead_tracker


def get_content_pipeline() -> ContentPipeline:
    global _content_pipeline
    if _content_pipeline is None:
        _content_pipeline = ContentPipeline()
    return _content_pipeline


def get_budget_tracker() -> BudgetTracker:
    global _budget_tracker
    if _budget_tracker is None:
        _budget_tracker = BudgetTracker()
    return _budget_tracker
