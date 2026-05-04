"""
JARVIS MAX — Intelligent Workflow Playbooks
==============================================
Template-driven workflow execution with adaptive step sequencing.

A playbook is a reusable, parameterized workflow template:
  - Defined steps with pre/post conditions
  - Adaptive branching based on step outcomes
  - Integration with approval system for gated steps
  - Learning: playbook effectiveness tracked over time

Not a second orchestrator — playbooks are CONSUMED BY MetaOrchestrator
as structured mission plans, not a parallel execution engine.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

log = structlog.get_logger()

_PLAYBOOK_DIR = os.environ.get("PLAYBOOK_DIR", "data/playbooks")


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class PlaybookStep:
    """A single step in a playbook."""
    id: str = ""
    name: str = ""
    description: str = ""
    agent_id: str = ""       # Which agent should execute
    tool: str = ""           # Primary tool to use
    parameters: Dict[str, Any] = field(default_factory=dict)
    pre_conditions: List[str] = field(default_factory=list)
    post_conditions: List[str] = field(default_factory=list)
    requires_approval: bool = False
    on_failure: str = "stop"  # stop | skip | retry | fallback
    fallback_step: str = ""   # step ID to use as fallback
    max_retries: int = 1
    timeout_s: int = 300

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "agent_id": self.agent_id, "tool": self.tool,
            "parameters": self.parameters,
            "requires_approval": self.requires_approval,
            "on_failure": self.on_failure, "timeout_s": self.timeout_s,
        }


@dataclass
class Playbook:
    """A reusable workflow template."""
    id: str = ""
    name: str = ""
    description: str = ""
    purpose: str = ""           # Human-readable purpose statement
    category: str = ""          # deployment, analysis, testing, business, security
    version: str = "1.0.0"
    steps: List[PlaybookStep] = field(default_factory=list)
    parameters: Dict[str, str] = field(default_factory=dict)  # name → description
    tags: List[str] = field(default_factory=list)
    # Structured metadata (Phase 8 requirements)
    required_capabilities: List[str] = field(default_factory=list)   # e.g., ["code.python", "deploy.docker"]
    required_secrets: List[str] = field(default_factory=list)        # Vault secret types needed
    required_connectors: List[str] = field(default_factory=list)     # Connector types needed
    risk_level: str = "low"                                          # none | low | medium | high | critical
    expected_outputs: List[str] = field(default_factory=list)        # What this playbook produces
    rollback_instructions: str = ""                                  # How to undo if aborted
    abort_policy: str = "safe_stop"                                  # safe_stop | immediate | rollback
    created_at: float = field(default_factory=time.time)
    # Tracking
    times_used: int = 0
    avg_success_rate: float = 0.0
    avg_duration_s: float = 0.0

    @property
    def approval_checkpoints(self) -> List[str]:
        """Steps that require approval."""
        return [s.id for s in self.steps if s.requires_approval]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "purpose": self.purpose,
            "category": self.category, "version": self.version,
            "steps": [s.to_dict() for s in self.steps],
            "parameters": self.parameters, "tags": self.tags,
            "required_capabilities": self.required_capabilities,
            "required_secrets": self.required_secrets,
            "required_connectors": self.required_connectors,
            "risk_level": self.risk_level,
            "expected_outputs": self.expected_outputs,
            "approval_checkpoints": self.approval_checkpoints,
            "rollback_instructions": self.rollback_instructions,
            "abort_policy": self.abort_policy,
            "times_used": self.times_used,
            "avg_success_rate": round(self.avg_success_rate, 2),
            "avg_duration_s": round(self.avg_duration_s, 1),
        }


@dataclass
class PlaybookExecution:
    """A running instance of a playbook."""
    playbook_id: str = ""
    execution_id: str = ""
    mission_id: str = ""
    current_step: int = 0
    step_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    resolved_params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "playbook_id": self.playbook_id,
            "execution_id": self.execution_id,
            "mission_id": self.mission_id,
            "current_step": self.current_step,
            "status": self.status,
            "step_results": self.step_results,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class PlaybookRegistry:
    """
    Manages playbook templates and their execution tracking.

    Playbooks are stored as JSON files in PLAYBOOK_DIR.
    MetaOrchestrator consumes playbooks as structured plans.
    """

    def __init__(self, playbook_dir: str = _PLAYBOOK_DIR):
        self._dir = Path(playbook_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._playbooks: Dict[str, Playbook] = {}
        self._executions: Dict[str, PlaybookExecution] = {}
        self._load_all()

    # ── Playbook management ──

    def register(self, playbook: Playbook) -> Playbook:
        self._playbooks[playbook.id] = playbook
        self._save(playbook)
        return playbook

    def get(self, playbook_id: str) -> Optional[Playbook]:
        return self._playbooks.get(playbook_id)

    def find(self, category: str = "", tags: Optional[List[str]] = None, query: str = "") -> List[Playbook]:
        results = []
        for pb in self._playbooks.values():
            if category and pb.category != category:
                continue
            if tags and not any(t in pb.tags for t in tags):
                continue
            if query and query.lower() not in pb.name.lower() and query.lower() not in pb.description.lower():
                continue
            results.append(pb)
        return sorted(results, key=lambda p: p.avg_success_rate, reverse=True)

    def list_all(self) -> List[Dict[str, Any]]:
        return [pb.to_dict() for pb in self._playbooks.values()]

    def remove(self, playbook_id: str) -> bool:
        if playbook_id in self._playbooks:
            del self._playbooks[playbook_id]
            fpath = self._dir / f"{playbook_id}.json"
            if fpath.exists():
                fpath.unlink()
            return True
        return False

    # ── Execution ──

    def create_execution(self, playbook_id: str, mission_id: str = "", params: Optional[Dict] = None) -> Optional[PlaybookExecution]:
        pb = self._playbooks.get(playbook_id)
        if not pb:
            return None
        exec_id = f"pbe-{int(time.time())}-{len(self._executions)}"
        execution = PlaybookExecution(
            playbook_id=playbook_id, execution_id=exec_id,
            mission_id=mission_id, resolved_params=params or {},
        )
        self._executions[exec_id] = execution
        pb.times_used += 1
        return execution

    def get_next_step(self, execution_id: str) -> Optional[PlaybookStep]:
        """Get the next step to execute."""
        exe = self._executions.get(execution_id)
        if not exe or exe.status != "running":
            return None
        pb = self._playbooks.get(exe.playbook_id)
        if not pb or exe.current_step >= len(pb.steps):
            return None
        return pb.steps[exe.current_step]

    def record_step_result(
        self, execution_id: str, step_id: str, success: bool, output: Any = None
    ) -> Optional[PlaybookStep]:
        """Record step result and determine next step."""
        exe = self._executions.get(execution_id)
        if not exe:
            return None
        pb = self._playbooks.get(exe.playbook_id)
        if not pb:
            return None
        exe.step_results[step_id] = {"success": success, "output": str(output)[:500]}
        current_step = pb.steps[exe.current_step] if exe.current_step < len(pb.steps) else None
        if not success and current_step:
            if current_step.on_failure == "stop":
                exe.status = "failed"
                exe.completed_at = time.time()
                self._update_stats(pb, exe)
                return None
            elif current_step.on_failure == "skip":
                pass  # Fall through to advance
            elif current_step.on_failure == "fallback" and current_step.fallback_step:
                for i, s in enumerate(pb.steps):
                    if s.id == current_step.fallback_step:
                        exe.current_step = i
                        return pb.steps[i]
        # Advance
        exe.current_step += 1
        if exe.current_step >= len(pb.steps):
            exe.status = "completed"
            exe.completed_at = time.time()
            self._update_stats(pb, exe)
            return None
        return pb.steps[exe.current_step]

    def _update_stats(self, pb: Playbook, exe: PlaybookExecution) -> None:
        success = exe.status == "completed"
        duration = exe.completed_at - exe.started_at
        if pb.times_used == 1:
            pb.avg_success_rate = 1.0 if success else 0.0
            pb.avg_duration_s = duration
        else:
            pb.avg_success_rate = pb.avg_success_rate * 0.8 + (1.0 if success else 0.0) * 0.2
            pb.avg_duration_s = pb.avg_duration_s * 0.8 + duration * 0.2

    # ── Persistence ──

    def _save(self, playbook: Playbook) -> None:
        try:
            fpath = self._dir / f"{playbook.id}.json"
            fpath.write_text(json.dumps(playbook.to_dict(), indent=2))
        except Exception as e:
            log.warning("playbook_save_failed", err=str(e))

    def _load_all(self) -> None:
        try:
            for fpath in self._dir.glob("*.json"):
                data = json.loads(fpath.read_text())
                steps = [PlaybookStep(**s) for s in data.get("steps", [])]
                pb = Playbook(
                    id=data["id"], name=data["name"], description=data.get("description", ""),
                    purpose=data.get("purpose", ""),
                    category=data.get("category", ""), version=data.get("version", "1.0.0"),
                    steps=steps, parameters=data.get("parameters", {}),
                    tags=data.get("tags", []),
                    required_capabilities=data.get("required_capabilities", []),
                    required_secrets=data.get("required_secrets", []),
                    required_connectors=data.get("required_connectors", []),
                    risk_level=data.get("risk_level", "low"),
                    expected_outputs=data.get("expected_outputs", []),
                    rollback_instructions=data.get("rollback_instructions", ""),
                    abort_policy=data.get("abort_policy", "safe_stop"),
                    times_used=data.get("times_used", 0),
                    avg_success_rate=data.get("avg_success_rate", 0),
                    avg_duration_s=data.get("avg_duration_s", 0),
                )
                self._playbooks[pb.id] = pb
        except Exception as e:
            log.warning("playbook_load_failed", err=str(e))

    # ── Built-in playbooks ──

    def seed_defaults(self) -> int:
        """Register built-in playbook templates. Returns count of seeded playbooks."""
        defaults = [
            Playbook(
                id="pb-code-review", name="Code Review",
                description="Systematic code review: read → analyze → report",
                purpose="Ensure code quality and catch bugs before merge",
                category="analysis", tags=["code", "review", "quality"],
                risk_level="low",
                required_capabilities=["code.python", "code.review"],
                expected_outputs=["quality_report", "issue_list"],
                rollback_instructions="No side effects — safe to abort at any step",
                abort_policy="safe_stop",
                steps=[
                    PlaybookStep(id="read", name="Read source", agent_id="coder", tool="read_file"),
                    PlaybookStep(id="analyze", name="Analyze quality", agent_id="reviewer", tool="analyze_code"),
                    PlaybookStep(id="report", name="Generate report", agent_id="reviewer", tool="write_report"),
                ],
            ),
            Playbook(
                id="pb-bug-fix", name="Bug Fix",
                description="Structured bug fix: reproduce → diagnose → fix → test → verify",
                purpose="Fix a reported bug with minimal regression risk",
                category="development", tags=["bug", "fix", "development"],
                risk_level="medium",
                required_capabilities=["code.python", "test.pytest"],
                expected_outputs=["fix_patch", "test_results", "verification"],
                rollback_instructions="Revert commit from fix step. Run tests to confirm clean state.",
                abort_policy="rollback",
                steps=[
                    PlaybookStep(id="reproduce", name="Reproduce bug", agent_id="qa"),
                    PlaybookStep(id="diagnose", name="Find root cause", agent_id="coder", tool="search_code"),
                    PlaybookStep(id="fix", name="Apply fix", agent_id="coder", tool="write_file", requires_approval=True),
                    PlaybookStep(id="test", name="Run tests", agent_id="qa", tool="run_tests"),
                    PlaybookStep(id="verify", name="Verify fix", agent_id="reviewer"),
                ],
            ),
            Playbook(
                id="pb-deploy", name="Safe Deployment",
                description="Staged deployment: test → build → deploy → verify → rollback-ready",
                purpose="Deploy code to production with safety gates and rollback",
                category="deployment", tags=["deploy", "release", "production"],
                risk_level="high",
                required_capabilities=["deploy.docker", "test.pytest"],
                required_secrets=["DOCKER_REGISTRY_TOKEN"],
                expected_outputs=["build_artifact", "deploy_confirmation", "smoke_test_result"],
                rollback_instructions="Run docker-compose down && git revert HEAD && docker-compose up -d",
                abort_policy="rollback",
                steps=[
                    PlaybookStep(id="test", name="Run full tests", agent_id="qa", tool="run_tests"),
                    PlaybookStep(id="build", name="Build artifacts", agent_id="devops"),
                    PlaybookStep(id="deploy", name="Deploy to staging", agent_id="devops", requires_approval=True),
                    PlaybookStep(id="verify", name="Smoke test staging", agent_id="qa"),
                    PlaybookStep(id="promote", name="Promote to production", agent_id="devops", requires_approval=True),
                ],
            ),
            Playbook(
                id="pb-si-patch", name="Self-Improvement Patch",
                description="Discover weakness → generate patch → sandbox test → review → promote",
                purpose="Autonomously improve codebase quality via safe patching",
                category="self-improvement", tags=["si", "patch", "autonomous"],
                risk_level="medium",
                required_capabilities=["code.python", "test.pytest", "code.review"],
                expected_outputs=["patch_diff", "test_results", "promotion_decision"],
                rollback_instructions="git checkout -- <patched_files>. Patch is never auto-applied to production.",
                abort_policy="safe_stop",
                steps=[
                    PlaybookStep(id="discover", name="Discover weakness", agent_id="watcher"),
                    PlaybookStep(id="patch", name="Generate patch", agent_id="coder"),
                    PlaybookStep(id="sandbox", name="Test in sandbox", agent_id="qa", tool="run_tests"),
                    PlaybookStep(id="review", name="Review patch", agent_id="reviewer", requires_approval=True),
                    PlaybookStep(id="promote", name="Promote decision", agent_id="devops"),
                ],
            ),
            Playbook(
                id="pb-module-install", name="Module Install + Health Check",
                description="Install module → check deps → test → verify health",
                purpose="Safely install and validate a new module",
                category="operations", tags=["module", "install", "health"],
                risk_level="low",
                required_capabilities=["modules.manage"],
                expected_outputs=["install_result", "health_report"],
                rollback_instructions="Disable or remove the installed module via module manager",
                abort_policy="safe_stop",
                steps=[
                    PlaybookStep(id="check_deps", name="Check dependencies", agent_id="devops"),
                    PlaybookStep(id="install", name="Install module", agent_id="devops", requires_approval=True),
                    PlaybookStep(id="test", name="Test module", agent_id="qa"),
                    PlaybookStep(id="health", name="Verify health", agent_id="watcher"),
                ],
            ),
            Playbook(
                id="pb-incident-triage", name="Incident Triage",
                description="Detect → classify → investigate → remediate → document",
                purpose="Structured incident response for production issues",
                category="operations", tags=["incident", "triage", "production"],
                risk_level="high",
                required_capabilities=["monitoring.logs", "code.python"],
                expected_outputs=["incident_report", "root_cause", "remediation_steps"],
                rollback_instructions="Revert any remediation changes. Escalate to human operator.",
                abort_policy="safe_stop",
                steps=[
                    PlaybookStep(id="detect", name="Gather symptoms", agent_id="watcher"),
                    PlaybookStep(id="classify", name="Classify severity", agent_id="reviewer"),
                    PlaybookStep(id="investigate", name="Root cause analysis", agent_id="coder"),
                    PlaybookStep(id="remediate", name="Apply fix", agent_id="coder", requires_approval=True),
                    PlaybookStep(id="document", name="Write incident report", agent_id="reviewer"),
                ],
            ),
        ]
        count = 0
        for pb in defaults:
            if pb.id not in self._playbooks:
                self.register(pb)
                count += 1
        return count
