"""
JARVIS MAX — Cognitive Bridge
==================================
Non-invasive integration layer that wires the 8 cognitive modules into
the runtime without modifying CRITICAL files.

This bridge is imported by runtime components and called at strategic points.
All calls are fail-open: if any module errors, the operation proceeds unchanged.

Wiring points:
  1. pre_mission()        → MetaCognition + DecisionConfidence + CapabilityGraph
  2. post_step()          → MemoryGraph + LearningTraces + AgentReputation
  3. post_mission()       → MemoryGraph + LearningTraces + AgentReputation
  4. score_decision()     → DecisionConfidence
  5. find_playbook()      → WorkflowPlaybooks
  6. get_module_marketplace() → InternalMarketplace enrichment

Singleton pattern: all modules lazily initialized, never crash on import.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger()

_DATA_DIR = os.environ.get("JARVISMAX_DATA_DIR", "data")


class CognitiveBridge:
    """
    Singleton bridge to all cognitive modules.
    
    Usage:
        bridge = get_bridge()
        analysis = bridge.pre_mission("Fix login bug", agent_id="coder")
        bridge.post_step(mission_id="m1", step_id="s1", agent_id="coder", success=True)
    """

    _instance: Optional["CognitiveBridge"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._initialized = False
        self._memory_graph = None
        self._reputation = None
        self._meta_cognition = None
        self._marketplace = None
        self._learning_traces = None
        self._capability_graph = None
        self._confidence = None
        self._playbooks = None

    @classmethod
    def get(cls) -> "CognitiveBridge":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def _ensure_init(self) -> None:
        """Lazy init all modules. Never raises."""
        if self._initialized:
            return
        self._initialized = True
        try:
            from core.memory_graph.graph_store import MemoryGraph
            self._memory_graph = MemoryGraph(
                persist_path=os.path.join(_DATA_DIR, "memory_graph.json")
            )
        except Exception as e:
            log.debug("cognitive_bridge.memory_graph_init_failed", err=str(e))

        try:
            from core.agent_reputation import ReputationTracker
            self._reputation = ReputationTracker(
                persist_path=os.path.join(_DATA_DIR, "agent_reputation.json")
            )
        except Exception as e:
            log.debug("cognitive_bridge.reputation_init_failed", err=str(e))

        try:
            from core.meta_cognition import MetaCognition
            self._meta_cognition = MetaCognition()
        except Exception as e:
            log.debug("cognitive_bridge.meta_cognition_init_failed", err=str(e))

        try:
            from core.internal_marketplace import InternalMarketplace
            self._marketplace = InternalMarketplace(
                catalog_path=os.path.join(_DATA_DIR, "marketplace.json")
            )
        except Exception as e:
            log.debug("cognitive_bridge.marketplace_init_failed", err=str(e))

        try:
            from core.learning_traces import LearningTraceStore
            self._learning_traces = LearningTraceStore(
                persist_path=os.path.join(_DATA_DIR, "learning_traces.json")
            )
        except Exception as e:
            log.debug("cognitive_bridge.learning_traces_init_failed", err=str(e))

        try:
            from core.capability_graph import CapabilityGraph
            self._capability_graph = CapabilityGraph()
            # Auto-populate from runtime registries
            counts = self._capability_graph.populate_from_runtime()
            log.info("cognitive_bridge.capability_graph_populated", **counts)
        except Exception as e:
            log.debug("cognitive_bridge.capability_graph_init_failed", err=str(e))

        try:
            from core.decision_confidence import DecisionConfidence
            self._confidence = DecisionConfidence(
                reputation_tracker=self._reputation,
                learning_traces=self._learning_traces,
            )
        except Exception as e:
            log.debug("cognitive_bridge.confidence_init_failed", err=str(e))

        try:
            from core.workflow_playbooks import PlaybookRegistry
            self._playbooks = PlaybookRegistry(
                playbook_dir=os.path.join(_DATA_DIR, "playbooks")
            )
            self._playbooks.seed_defaults()
        except Exception as e:
            log.debug("cognitive_bridge.playbooks_init_failed", err=str(e))

        # Sync capability graph with reputation
        if self._capability_graph and self._reputation:
            try:
                self._capability_graph.update_reliability_from_reputation(self._reputation)
            except Exception:
                _silent_log.debug("suppressed_exception", src='cognitive_bridge.py')

    # ──────────────────────────────────────────────────────────────
    # 1. PRE-MISSION — called before mission execution starts
    # ──────────────────────────────────────────────────────────────

    def pre_mission(
        self,
        goal: str,
        agent_id: str = "",
        candidates: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Pre-mission cognitive analysis. Returns enriched metadata.
        Called from MetaOrchestrator.run_mission() or API layer.
        Never blocks on error.
        """
        self._ensure_init()
        result: Dict[str, Any] = {}

        # MetaCognition: task analysis
        if self._meta_cognition:
            try:
                analysis = self._meta_cognition.analyze(goal, context=context)
                result["meta_cognition"] = analysis.to_dict()
            except Exception as e:
                log.debug("cognitive_bridge.pre_mission.meta_cognition_failed", err=str(e))

        # DecisionConfidence: agent selection
        if self._confidence and agent_id and candidates:
            try:
                score = self._confidence.score_agent_selection(
                    agent_id, candidates, task_context=goal[:100]
                )
                result["agent_confidence"] = score.to_dict()
            except Exception as e:
                log.debug("cognitive_bridge.pre_mission.confidence_failed", err=str(e))

        # CapabilityGraph: find gaps
        if self._capability_graph:
            try:
                agents = self._capability_graph.find_agents_for_task(goal.split()[:5])
                if agents:
                    result["capability_routing"] = agents[:3]
            except Exception as e:
                log.debug("cognitive_bridge.pre_mission.capability_failed", err=str(e))

        # LearningTraces: relevant lessons
        if self._learning_traces:
            try:
                insights = self._learning_traces.get_insights_for(agent_id or "general")
                if insights:
                    result["relevant_lessons"] = [
                        {"lesson": i.get("actionable_insight", ""), "confidence": i.get("confidence", 0)}
                        for i in insights[:3]
                    ]
            except Exception as e:
                log.debug("cognitive_bridge.pre_mission.traces_failed", err=str(e))

        # MemoryGraph: link mission node
        if self._memory_graph:
            try:
                from core.memory_graph.graph_linker import GraphLinker
                linker = GraphLinker(self._memory_graph)
                linker.link_mission(goal[:16].replace(" ", "_"), label=goal[:80])
            except Exception as e:
                log.debug("cognitive_bridge.pre_mission.graph_failed", err=str(e))

        return result

    # ──────────────────────────────────────────────────────────────
    # 2. POST-STEP — called after each mission step completes
    # ──────────────────────────────────────────────────────────────

    def post_step(
        self,
        mission_id: str,
        step_id: str,
        agent_id: str,
        success: bool,
        latency_ms: float = 0,
        cost_usd: float = 0,
        error: str = "",
        output: str = "",
    ) -> None:
        """Record step outcome across cognitive modules. Never raises."""
        self._ensure_init()

        # AgentReputation
        if self._reputation:
            try:
                if success:
                    self._reputation.record_success(agent_id, latency_ms=latency_ms, cost_usd=cost_usd)
                else:
                    self._reputation.record_failure(agent_id, error_type=error[:50])
            except Exception as e:
                log.debug("cognitive_bridge.post_step.reputation_failed", err=str(e))

        # MemoryGraph
        if self._memory_graph:
            try:
                from core.memory_graph.graph_linker import GraphLinker
                linker = GraphLinker(self._memory_graph)
                linker.link_step(mission_id, step_id, agent_id=agent_id, label=f"step-{step_id}")
                linker.link_outcome(step_id, f"out-{step_id}", success=success,
                                    label="success" if success else error[:50])
            except Exception as e:
                log.debug("cognitive_bridge.post_step.graph_failed", err=str(e))

    # ──────────────────────────────────────────────────────────────
    # 3. POST-MISSION — called when mission completes or fails
    # ──────────────────────────────────────────────────────────────

    def post_mission(
        self,
        mission_id: str,
        goal: str,
        success: bool,
        agent_id: str = "",
        duration_s: float = 0,
        error: str = "",
        lessons_learned: Optional[List[str]] = None,
    ) -> None:
        """Record mission completion across cognitive modules. Never raises."""
        self._ensure_init()

        # LearningTraces
        if self._learning_traces:
            try:
                from core.learning_traces import LearningTrace, TraceType
                trace_type = TraceType.MISSION_SUCCESS if success else TraceType.MISSION_FAILURE
                self._learning_traces.record(LearningTrace(
                    type=trace_type,
                    event_description=f"Mission '{goal[:60]}' {'succeeded' if success else 'failed'}",
                    root_cause=error[:200] if error else "completed normally",
                    lesson="; ".join(lessons_learned[:3]) if lessons_learned else "",
                    applicable_to=[agent_id] if agent_id else [],
                    confidence=0.8 if success else 0.6,
                ))
            except Exception as e:
                log.debug("cognitive_bridge.post_mission.traces_failed", err=str(e))

        # MemoryGraph: link outcome
        if self._memory_graph:
            try:
                from core.memory_graph.graph_linker import GraphLinker
                linker = GraphLinker(self._memory_graph)
                linker.link_outcome(
                    mission_id, f"result-{mission_id}",
                    success=success, label="completed" if success else error[:50]
                )
            except Exception as e:
                log.debug("cognitive_bridge.post_mission.graph_failed", err=str(e))

        # Persist reputation
        if self._reputation:
            try:
                self._reputation.save()
            except Exception:
                _silent_log.debug("suppressed_exception", src='cognitive_bridge.py')

    # ──────────────────────────────────────────────────────────────
    # 4. DECISION SCORING — callable from any routing point
    # ──────────────────────────────────────────────────────────────

    def score_decision(
        self,
        decision_type: str,
        chosen: str,
        alternatives: Optional[List[str]] = None,
        context: str = "",
        risk_level: str = "low",
        agent_id: str = "",
        budget: str = "",
    ) -> Dict[str, Any]:
        """Score any routing/approval decision. Returns confidence dict."""
        self._ensure_init()
        if not self._confidence:
            return {"score": 0.5, "reasoning": "confidence module unavailable"}
        try:
            if decision_type == "agent":
                score = self._confidence.score_agent_selection(
                    chosen, alternatives or [chosen], task_context=context
                )
            elif decision_type == "model":
                score = self._confidence.score_model_selection(
                    chosen, task_type=context, budget=budget
                )
            elif decision_type == "approval":
                score = self._confidence.score_approval_recommendation(
                    chosen, risk_level=risk_level, agent_id=agent_id
                )
            else:
                return {"score": 0.5, "reasoning": f"unknown decision type: {decision_type}"}
            return score.to_dict()
        except Exception as e:
            log.debug("cognitive_bridge.score_decision_failed", err=str(e))
            return {"score": 0.5, "reasoning": f"scoring failed: {e}"}

    # ──────────────────────────────────────────────────────────────
    # 5. PLAYBOOKS — find and manage workflow templates
    # ──────────────────────────────────────────────────────────────

    def find_playbook(
        self,
        category: str = "",
        tags: Optional[List[str]] = None,
        query: str = "",
    ) -> List[Dict[str, Any]]:
        """Find matching playbooks."""
        self._ensure_init()
        if not self._playbooks:
            return []
        try:
            results = self._playbooks.find(category=category, tags=tags, query=query)
            return [p.to_dict() for p in results]
        except Exception as e:
            log.debug("cognitive_bridge.find_playbook_failed", err=str(e))
            return []

    def start_playbook(
        self, playbook_id: str, mission_id: str = "", params: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """Start executing a playbook. Returns execution dict."""
        self._ensure_init()
        if not self._playbooks:
            return None
        try:
            exe = self._playbooks.create_execution(playbook_id, mission_id, params)
            return exe.to_dict() if exe else None
        except Exception as e:
            log.debug("cognitive_bridge.start_playbook_failed", err=str(e))
            return None

    # ──────────────────────────────────────────────────────────────
    # 6. MARKETPLACE — enriched module catalog
    # ──────────────────────────────────────────────────────────────

    def marketplace_search(self, query: str = "", type: str = "") -> List[Dict[str, Any]]:
        """Search internal marketplace."""
        self._ensure_init()
        if not self._marketplace:
            return []
        try:
            results = self._marketplace.search(query=query, type=type)
            return [r.to_dict() for r in results]
        except Exception as e:
            log.debug("cognitive_bridge.marketplace_search_failed", err=str(e))
            return []

    # ──────────────────────────────────────────────────────────────
    # 7. DIRECT MODULE ACCESS (for API routes)
    # ──────────────────────────────────────────────────────────────

    @property
    def memory_graph(self):
        self._ensure_init()
        return self._memory_graph

    @property
    def reputation(self):
        self._ensure_init()
        return self._reputation

    @property
    def meta_cognition(self):
        self._ensure_init()
        return self._meta_cognition

    @property
    def marketplace(self):
        self._ensure_init()
        return self._marketplace

    @property
    def learning_traces(self):
        self._ensure_init()
        return self._learning_traces

    @property
    def capability_graph(self):
        self._ensure_init()
        return self._capability_graph

    @property
    def confidence(self):
        self._ensure_init()
        return self._confidence

    @property
    def playbooks(self):
        self._ensure_init()
        return self._playbooks

    def stats(self) -> Dict[str, Any]:
        """Full cognitive system stats."""
        self._ensure_init()
        result: Dict[str, Any] = {"modules_available": 0}
        for name, mod in [
            ("memory_graph", self._memory_graph),
            ("reputation", self._reputation),
            ("meta_cognition", self._meta_cognition),
            ("marketplace", self._marketplace),
            ("learning_traces", self._learning_traces),
            ("capability_graph", self._capability_graph),
            ("confidence", self._confidence),
            ("playbooks", self._playbooks),
        ]:
            if mod is not None:
                result["modules_available"] += 1
                try:
                    if hasattr(mod, "stats"):
                        result[name] = mod.stats()
                    elif hasattr(mod, "calibration_report"):
                        result[name] = mod.calibration_report()
                    else:
                        result[name] = {"status": "ok"}
                except Exception:
                    result[name] = {"status": "error"}
            else:
                result[name] = {"status": "unavailable"}
        return result


def get_bridge() -> CognitiveBridge:
    """Get the singleton CognitiveBridge instance."""
    return CognitiveBridge.get()
