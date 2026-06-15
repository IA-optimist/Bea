"""
BEA — Workflow Primitives (section 10)
Reusable workflow template storage and retrieval.
"""
from __future__ import annotations

import os
import time
import structlog
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = structlog.get_logger("bea.operating_primitives")

# ═══════════════════════════════════════════════════════════════
# 10. WORKFLOW TEMPLATES
# ═══════════════════════════════════════════════════════════════

@dataclass
class WorkflowTemplate:
    """Reusable workflow structure."""
    template_id: str = ""
    name: str = ""
    mission_type: str = ""
    phases: list = field(default_factory=list)  # ["research", "decision", "execution", "verification"]
    tools_per_phase: dict = field(default_factory=dict)
    success_rate: float = 0.0
    uses: int = 0
    last_used: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Standard workflow phases
STANDARD_PHASES = ["research", "decision", "execution", "verification", "iteration"]
MAX_WORKFLOW_DEPTH = 10  # Max phases per workflow


class WorkflowTemplateStore:
    """Store and retrieve proven workflow templates."""
    MAX_TEMPLATES = 50
    PERSIST_FILE = "workspace/workflow_templates.json"

    def __init__(self, persist_path: Optional[str] = None):
        self._templates: dict[str, WorkflowTemplate] = {}
        self._persist_path = persist_path or self.PERSIST_FILE
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()
            self._loaded = True

    def record_successful_workflow(
        self,
        mission_type: str,
        tools_used: list[str],
        phases_executed: list[str],
    ):
        """Record a successful workflow as a template."""
        self._ensure_loaded()
        key = f"{mission_type}:{','.join(sorted(set(phases_executed)))}"
        if key in self._templates:
            t = self._templates[key]
            t.uses += 1
            t.success_rate = min(1.0, t.success_rate + 0.05)
            t.last_used = time.time()
        else:
            if len(self._templates) >= self.MAX_TEMPLATES:
                oldest_key = min(self._templates, key=lambda k: self._templates[k].last_used)
                del self._templates[oldest_key]
            import uuid
            t = WorkflowTemplate(
                template_id=str(uuid.uuid4())[:8],
                name=f"{mission_type} workflow",
                mission_type=mission_type,
                phases=phases_executed[:MAX_WORKFLOW_DEPTH],
                tools_per_phase={p: tools_used for p in phases_executed},
                success_rate=0.6,
                uses=1,
                last_used=time.time(),
            )
            self._templates[key] = t
        self.save()

    def get_best_template(self, mission_type: str) -> Optional[WorkflowTemplate]:
        """Get the most effective template for a mission type."""
        self._ensure_loaded()
        candidates = [
            t for t in self._templates.values()
            if t.mission_type == mission_type and t.uses >= 2
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda t: t.success_rate * t.uses)

    def get_all(self) -> list[dict]:
        self._ensure_loaded()
        return [t.to_dict() for t in sorted(
            self._templates.values(), key=lambda t: t.uses, reverse=True
        )[:20]]

    def save(self):
        try:
            import json
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._templates.items()}, f, indent=2)
        except Exception as e:
            logger.warning("workflow_save_failed: %s", str(e)[:80])

    def load(self):
        import json
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for key, d in data.items():
                self._templates[key] = WorkflowTemplate(
                    **{k: v for k, v in d.items() if k in WorkflowTemplate.__dataclass_fields__}
                )
        except Exception as e:
            logger.warning("workflow_load_failed: %s", str(e)[:80])


_workflow_store: Optional[WorkflowTemplateStore] = None

def get_workflow_store() -> WorkflowTemplateStore:
    global _workflow_store
    if _workflow_store is None:
        _workflow_store = WorkflowTemplateStore()
    return _workflow_store
