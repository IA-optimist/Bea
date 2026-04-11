"""
JARVIS — Performance Intelligence API
=========================================
Exposes tool and mission performance data to the Jarvis app.
All endpoints fail-open with sensible defaults.

Endpoints:
    GET /api/v3/performance/tools          — tool health dashboard
    GET /api/v3/performance/tools/{name}   — single tool detail
    GET /api/v3/performance/missions       — mission performance dashboard
    GET /api/v3/performance/missions/{type} — single mission type strategy
    GET /api/v3/performance/agents         — agent performance data
    GET /api/v3/performance/overview       — combined overview for cockpit
    POST /api/v3/performance/improvement   — submit improvement proposal
    GET /api/v3/performance/improvements   — list improvement proposals
"""
from __future__ import annotations

import logging
import time
from typing import Optional

try:
    from fastapi import APIRouter, Body, Depends, Header, Query
    from fastapi.responses import JSONResponse
except ImportError:
    APIRouter = None

from api._deps import _check_auth
from typing import Optional as _Opt
_silent_log = __import__("structlog").get_logger(__name__)

def _auth(x_jarvis_token: _Opt[str] = Header(None), authorization: _Opt[str] = Header(None)):
    _check_auth(x_jarvis_token, authorization)

logger = logging.getLogger("jarvis.api.performance")


def _ok(data, status: int = 200):
    return JSONResponse({"ok": True, "data": data}, status_code=status)


def _err(msg: str, status: int = 500):
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


if APIRouter:
    router = APIRouter(prefix="/api/v3/performance", tags=["performance"], dependencies=[Depends(_auth)])
else:
    router = None


if router:

    @router.get("/tools")
    def get_tool_performance():
        """Tool health dashboard — reliability, latency, failure patterns."""
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            tracker = get_tool_performance_tracker()
            return _ok(tracker.get_dashboard_data())
        except ImportError:
            return _ok({
                "summary": {"total_tools_tracked": 0},
                "tools": [],
                "failing_tools": [],
                "reliability_ranking": [],
            })
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/tools/{tool_name}")
    def get_tool_detail(tool_name: str):
        """Single tool performance detail."""
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            tracker = get_tool_performance_tracker()
            stats = tracker.get_stats(tool_name)
            if stats:
                return _ok(stats.to_dict())
            return _err(f"No data for tool: {tool_name}", status=404)
        except ImportError:
            return _err("Tool tracker not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/missions")
    def get_mission_performance():
        """Mission performance dashboard — by type, agent, recent outcomes."""
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            return _ok(tracker.get_dashboard_data())
        except ImportError:
            return _ok({
                "summary": {"total_missions_tracked": 0},
                "by_type": [],
                "agent_performance": [],
                "recent_outcomes": [],
            })
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/missions/{mission_type}")
    def get_mission_type_strategy(mission_type: str):
        """Best-known strategy for a mission type based on historical data."""
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            strategy = tracker.get_strategy_for_type(mission_type)
            if strategy:
                return _ok(strategy)
            return _ok({"mission_type": mission_type, "sample_size": 0, "note": "No data yet"})
        except ImportError:
            return _err("Mission tracker not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/agents")
    def get_agent_performance():
        """Agent performance — per-agent success rates and domain specialization."""
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            tracker = get_mission_performance_tracker()
            data = tracker.get_dashboard_data()
            return _ok({
                "agents": data.get("agent_performance", []),
                "summary": {"agents_tracked": data["summary"]["agents_tracked"]},
            })
        except ImportError:
            return _ok({"agents": [], "summary": {"agents_tracked": 0}})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/agents/specialization")
    def get_agent_specialization():
        """Agent specialization map — domain performance, reliability, best/worst domains."""
        try:
            from core.dynamic_agent_router import get_agent_specialization_map
            return _ok(get_agent_specialization_map())
        except ImportError:
            return _ok({"agents": [], "data_sufficient": False})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/routing/explain/{mission_type}")
    def explain_routing(mission_type: str, complexity: str = Query("medium")):
        """Explain agent routing decision for a mission type."""
        try:
            from core.dynamic_agent_router import get_routing_explanation
            # Get static candidates
            from agents.crew import MISSION_ROUTING
            static = MISSION_ROUTING.get(mission_type, ["scout-research"])
            return _ok(get_routing_explanation(mission_type, complexity, static))
        except ImportError:
            return _ok({"routing_mode": "static", "agents": []})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/tools/gaps")
    def get_tool_gaps():
        """Analyze tool ecosystem for gaps and missing capabilities."""
        try:
            from core.tool_gap_analyzer import analyze_tool_gaps
            return _ok(analyze_tool_gaps())
        except ImportError:
            return _ok([])
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/memory/strategies")
    def get_mission_strategies():
        """Cross-mission strategy memory — what works, what fails."""
        try:
            from core.mission_memory import get_mission_memory
            return _ok(get_mission_memory().get_dashboard_data())
        except ImportError:
            return _ok({"total_strategies": 0, "top_strategies": []})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/overview")
    def get_performance_overview():
        """Combined overview for cockpit main screen."""
        overview = {
            "timestamp": time.time(),
            "tool_health": {},
            "mission_health": {},
            "agent_health": {},
            "improvement_proposals": [],
        }

        # Tool health
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            td = get_tool_performance_tracker().get_dashboard_data()
            overview["tool_health"] = td.get("summary", {})
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        # Mission health
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            md = get_mission_performance_tracker().get_dashboard_data()
            overview["mission_health"] = md.get("summary", {})
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        # Agent health
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            md = get_mission_performance_tracker().get_dashboard_data()
            agents = md.get("agent_performance", [])
            overview["agent_health"] = {
                "agents_tracked": len(agents),
                "top_performers": [
                    {"agent": a["agent"], "rate": a["success_rate"]}
                    for a in sorted(agents, key=lambda x: x["success_rate"], reverse=True)[:5]
                ],
            }
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        # Mission memory
        try:
            from core.mission_memory import get_mission_memory
            mm = get_mission_memory().get_dashboard_data()
            overview["strategy_memory"] = {
                "strategies": mm.get("total_strategies", 0),
                "effective": mm.get("effective_strategies", 0),
                "failing_patterns": mm.get("failing_patterns", 0),
            }
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        # Tool gaps
        try:
            from core.tool_gap_analyzer import analyze_tool_gaps
            gaps = analyze_tool_gaps()
            overview["tool_gaps"] = len(gaps)
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        # Improvement proposals
        try:
            from core.improvement_proposals import get_proposal_store
            proposals = get_proposal_store().list_pending()
            overview["improvement_proposals"] = proposals[:10]
        except Exception:
            _silent_log.debug("suppressed_exception", src='performance.py')

        return _ok(overview)

    # ── Improvement Proposals ──────────────────────────────────────────────

    @router.post("/improvement")
    def submit_improvement_proposal(body: dict = {}):
        """Submit an improvement proposal for review."""
        try:
            from core.improvement_proposals import get_proposal_store, ImprovementProposal
            proposal = ImprovementProposal(
                proposal_type=body.get("type", "unknown"),
                title=body.get("title", ""),
                description=body.get("description", ""),
                affected_components=body.get("components", []),
                estimated_benefit=body.get("benefit", ""),
                risk_score=body.get("risk_score", 5),
                source=body.get("source", "manual"),
            )
            pid = get_proposal_store().add(proposal)
            return _ok({"proposal_id": pid}, status=201)
        except ImportError:
            return _err("Proposal store not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/improvements")
    def list_improvement_proposals(
        status: Optional[str] = Query(None),
        limit: int = Query(20, ge=1, le=100),
    ):
        """List improvement proposals, optionally filtered by status."""
        try:
            from core.improvement_proposals import get_proposal_store
            store = get_proposal_store()
            if status == "pending":
                proposals = store.list_pending()
            elif status == "approved":
                proposals = store.list_approved()
            elif status == "rejected":
                proposals = store.list_rejected()
            else:
                proposals = store.list_all()
            return _ok(proposals[:limit])
        except ImportError:
            return _ok([])
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/improvements/{proposal_id}/approve")
    def approve_proposal(proposal_id: str):
        """Approve an improvement proposal."""
        try:
            from core.improvement_proposals import get_proposal_store
            ok = get_proposal_store().approve(proposal_id)
            if ok:
                return _ok({"status": "approved"})
            return _err("Proposal not found or already processed", status=404)
        except ImportError:
            return _err("Proposal store not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/improvements/{proposal_id}/reject")
    def reject_proposal(proposal_id: str, body: dict = {}):
        """Reject an improvement proposal."""
        try:
            from core.improvement_proposals import get_proposal_store
            ok = get_proposal_store().reject(proposal_id, reason=body.get("reason", ""))
            if ok:
                return _ok({"status": "rejected"})
            return _err("Proposal not found or already processed", status=404)
        except ImportError:
            return _err("Proposal store not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    # ── Execution Engine Telemetry ────────────────────────────────────

    @router.get("/execution/telemetry")
    def get_execution_telemetry(limit: int = Query(20, ge=1, le=100)):
        """Recent execution telemetry with per-step detail."""
        try:
            from core.execution_engine import get_recent_telemetry, get_telemetry_summary
            return _ok({
                "summary": get_telemetry_summary(),
                "recent": get_recent_telemetry(limit),
            })
        except ImportError:
            return _ok({"summary": {"total_missions": 0}, "recent": []})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/execution/evaluations")
    def get_execution_evaluations(limit: int = Query(20, ge=1, le=100)):
        """Mission quality evaluations with trend data."""
        try:
            from core.execution_engine import get_evaluation_history, get_evaluation_trends
            return _ok({
                "trends": get_evaluation_trends(),
                "recent": get_evaluation_history(limit),
            })
        except ImportError:
            return _ok({"trends": {"total": 0}, "recent": []})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/execution/recovery")
    def get_recovery_stats():
        """Recovery strategy effectiveness."""
        try:
            from core.execution_engine import get_recovery_stats
            return _ok(get_recovery_stats())
        except ImportError:
            return _ok({"total_strategies": 0, "successful": 0})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/safety")
    def get_safety_state():
        """Current safety control state — all kill switches and feature flags."""
        try:
            from core.safety_controls import get_safety_state
            return _ok(get_safety_state().to_dict())
        except ImportError:
            return _ok({"note": "safety_controls not available"})
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/lifecycle/validate")
    def validate_lifecycle(body: dict = {}):
        """Validate mission lifecycle completeness."""
        try:
            from core.safety_controls import validate_lifecycle
            steps = body.get("steps", [])
            return _ok(validate_lifecycle(steps))
        except ImportError:
            return _err("safety_controls not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/lifecycle")
    def get_lifecycle_data():
        """Mission lifecycle completeness dashboard."""
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            return _ok(get_lifecycle_tracker().get_dashboard_data())
        except ImportError:
            return _ok({"total": 0, "recent": []})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/lifecycle/{mission_id}")
    def get_mission_lifecycle(mission_id: str):
        """Lifecycle record for a specific mission."""
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            rec = get_lifecycle_tracker().get(mission_id)
            if rec:
                return _ok(rec.to_dict())
            return _err("Mission not found", status=404)
        except ImportError:
            return _err("Lifecycle tracker not available", status=503)
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/confidence")
    def get_system_confidence():
        """System confidence indicators — composite health signal."""
        confidence = {"score": 0.5, "signals": {}}
        scores = []

        # Tool health confidence
        try:
            from core.tool_performance_tracker import get_tool_performance_tracker
            t = get_tool_performance_tracker()
            d = t.get_dashboard_data()
            s = d.get("summary", {})
            total = s.get("total_tools_tracked", 0)
            healthy = s.get("healthy", 0)
            tool_conf = healthy / max(total, 1) if total else 0.5
            confidence["signals"]["tool_health"] = round(tool_conf, 3)
            scores.append(tool_conf)
        except Exception:
            confidence["signals"]["tool_health"] = 0.5
            scores.append(0.5)

        # Mission success confidence
        try:
            from core.mission_performance_tracker import get_mission_performance_tracker
            m = get_mission_performance_tracker()
            d = m.get_dashboard_data()
            s = d.get("summary", {})
            mission_conf = s.get("overall_success_rate", 0.5)
            confidence["signals"]["mission_success"] = round(mission_conf, 3)
            scores.append(mission_conf)
        except Exception:
            confidence["signals"]["mission_success"] = 0.5
            scores.append(0.5)

        # Execution stability confidence
        try:
            from core.execution_engine import get_telemetry_summary
            tel = get_telemetry_summary()
            stability = tel.get("avg_stability", 0.5)
            confidence["signals"]["execution_stability"] = round(stability, 3)
            scores.append(stability)
        except Exception:
            confidence["signals"]["execution_stability"] = 0.5
            scores.append(0.5)

        # Lifecycle completeness
        try:
            from core.lifecycle_tracker import get_lifecycle_tracker
            lc = get_lifecycle_tracker().get_dashboard_data()
            lc_conf = lc.get("complete_rate", 0.5)
            confidence["signals"]["lifecycle_completeness"] = round(lc_conf, 3)
            scores.append(lc_conf)
        except Exception:
            confidence["signals"]["lifecycle_completeness"] = 0.5
            scores.append(0.5)

        confidence["score"] = round(sum(scores) / max(len(scores), 1), 3)
        confidence["level"] = (
            "high" if confidence["score"] >= 0.8 else
            "medium" if confidence["score"] >= 0.5 else "low"
        )
        return _ok(confidence)

    @router.post("/detect")
    def run_detection():
        """Run improvement detection and store proposals."""
        try:
            from core.improvement_detector import detect_improvements
            proposals = detect_improvements(dry_run=False)
            return _ok(proposals)
        except ImportError:
            return _ok([])
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/execution/limits")
    def get_execution_limits():
        """Return configurable execution limits."""
        try:
            from core.execution_engine import get_execution_limits as _gel
            return _ok(_gel())
        except ImportError:
            return _ok({})
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/missions/{mission_id}/cancel")
    def cancel_mission(mission_id: str):
        """Cancel a running or pending mission."""
        try:
            from core.mission_system import get_mission_system
            ms = get_mission_system()
            result = ms.cancel(mission_id, reason="user_cancel_via_api")
            if result is None:
                return _err(f"Mission {mission_id} not found")
            return _ok({"mission_id": mission_id, "status": str(result.status)})
        except ImportError:
            return _err("mission_system not available")
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/architecture/ownership")
    def get_architecture_ownership():
        """Return architecture ownership map and known duplications."""
        try:
            from core.architecture_ownership import validate_ownership
            return _ok(validate_ownership())
        except ImportError:
            return _ok({"valid": True, "duplications": []})
        except Exception as e:
            return _err(str(e)[:200])

    # ── Operating Primitives ─────────────────────────────────────

    @router.post("/operating/feasibility")
    def check_feasibility(body: dict = Body(default={})):
        """Score mission feasibility."""
        try:
            from core.operating_primitives import score_feasibility
            result = score_feasibility(
                goal=body.get("goal", ""),
                mission_type=body.get("mission_type", "info_query"),
                required_tools=body.get("tools", []),
                complexity=body.get("complexity", "medium"),
            )
            return _ok(result.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/operating/value")
    def estimate_mission_value(body: dict = Body(default={})):
        """Estimate mission value."""
        try:
            from core.operating_primitives import estimate_value
            result = estimate_value(
                goal=body.get("goal", ""),
                mission_type=body.get("mission_type", "info_query"),
                complexity=body.get("complexity", "medium"),
                plan_steps=body.get("plan_steps", 1),
                risk_score=body.get("risk_score", 0),
            )
            return _ok(result.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/operating/strategy")
    def select_mission_strategy(body: dict = Body(default={})):
        """Select best strategy for a mission."""
        try:
            from core.operating_primitives import select_strategy
            result = select_strategy(
                goal=body.get("goal", ""),
                mission_type=body.get("mission_type", "info_query"),
                complexity=body.get("complexity", "medium"),
            )
            return _ok(result.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/signals")
    def get_op_signals():
        """Get operational intelligence signals."""
        try:
            from core.operating_primitives import get_operational_signals
            return _ok(get_operational_signals())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/objectives")
    def get_objectives():
        """Get persistent objectives dashboard."""
        try:
            from core.operating_primitives import get_objective_tracker
            return _ok(get_objective_tracker().get_dashboard())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/operating/economics")
    def compute_mission_economics(body: dict = Body(default={})):
        """Compute full economic estimate for a mission."""
        try:
            from core.operating_primitives import compute_economics
            result = compute_economics(
                goal=body.get("goal", ""),
                mission_type=body.get("mission_type", "info_query"),
                complexity=body.get("complexity", "medium"),
                plan_steps=body.get("plan_steps", 1),
                risk_score=body.get("risk_score", 0),
                required_tools=body.get("tools", []),
            )
            return _ok(result.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/portfolio")
    def get_portfolio():
        """Get objective portfolio summary."""
        try:
            from core.operating_primitives import ObjectivePortfolio
            portfolio = ObjectivePortfolio()
            return _ok(portfolio.get_portfolio_summary())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/opportunities")
    def get_opportunities():
        """Get advisory opportunity suggestions."""
        try:
            from core.operating_primitives import detect_opportunities
            return _ok([s.to_dict() for s in detect_opportunities()])
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/workflows")
    def get_workflows():
        """Get proven workflow templates."""
        try:
            from core.operating_primitives import get_workflow_store
            return _ok(get_workflow_store().get_all())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/approval")
    def get_approval_state():
        """Get approval gating configuration."""
        try:
            from core.operating_primitives import get_approval_status
            return _ok(get_approval_status())
        except Exception as e:
            return _err(str(e)[:200])

    # ── Connectors ───────────────────────────────────────────────

    @router.get("/connectors")
    def list_available_connectors():
        """List all available connectors with specs."""
        try:
            from core.connectors import list_connectors
            return _ok(list_connectors())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/connectors/{name}/execute")
    def execute_connector_endpoint(name: str, body: dict = Body(default={})):
        """Execute a connector by name."""
        try:
            from core.connectors import execute_connector
            result = execute_connector(name, body)
            return _ok(result.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/connectors/audit")
    def get_connector_audit():
        """Get connector approval audit trail."""
        try:
            from core.connectors import get_approval_audit
            return _ok(get_approval_audit())
        except Exception as e:
            return _err(str(e)[:200])

    # ── Workflow Runtime ─────────────────────────────────────────

    @router.get("/workflows/dashboard")
    def workflow_dashboard():
        """Full workflow runtime dashboard."""
        try:
            from core.workflow_runtime import (
                get_workflow_engine, get_scheduler, get_version_manager,
                get_event_manager, get_workflow_dashboard,
            )
            return _ok(get_workflow_dashboard(
                get_workflow_engine(), get_scheduler(),
                get_version_manager(), get_event_manager(),
            ))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/workflows/create")
    def create_workflow(body: dict = Body(default={})):
        """Create a new workflow execution."""
        try:
            from core.workflow_runtime import get_workflow_engine
            engine = get_workflow_engine()
            wf = engine.create_workflow(
                name=body.get("name", "unnamed"),
                steps=body.get("steps", []),
                version=body.get("version", 1),
                metadata=body.get("metadata", {}),
            )
            return _ok(wf.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/workflows/{execution_id}/run")
    def run_workflow(execution_id: str):
        """Run all remaining steps in a workflow."""
        try:
            from core.workflow_runtime import get_workflow_engine
            return _ok(get_workflow_engine().run_all(execution_id))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/workflows/{execution_id}/pause")
    def pause_workflow(execution_id: str):
        """Pause a running workflow."""
        try:
            from core.workflow_runtime import get_workflow_engine
            return _ok({"paused": get_workflow_engine().pause(execution_id)})
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/workflows/{execution_id}/resume")
    def resume_workflow(execution_id: str):
        """Resume a paused workflow."""
        try:
            from core.workflow_runtime import get_workflow_engine
            return _ok({"resumed": get_workflow_engine().resume(execution_id)})
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/workflows/{execution_id}/cancel")
    def cancel_workflow(execution_id: str):
        """Cancel a workflow."""
        try:
            from core.workflow_runtime import get_workflow_engine
            return _ok({"cancelled": get_workflow_engine().cancel(execution_id)})
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/workflows/{execution_id}")
    def get_workflow_detail(execution_id: str):
        """Get workflow execution details."""
        try:
            from core.workflow_runtime import get_workflow_engine
            wf = get_workflow_engine().get_execution(execution_id)
            return _ok(wf) if wf else _err("not found")
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/workflows/scheduled/tasks")
    def list_scheduled_tasks():
        """List all scheduled tasks."""
        try:
            from core.workflow_runtime import get_scheduler
            return _ok(get_scheduler().list_tasks())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/workflows/resources")
    def workflow_resources():
        """Get workflow resource pressure signals."""
        try:
            from core.workflow_runtime import (
                get_workflow_engine, get_scheduler, ResourceMonitor,
            )
            monitor = ResourceMonitor(get_workflow_engine(), get_scheduler())
            return _ok(monitor.get_signals())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/workflows/autonomy")
    def workflow_autonomy():
        """Get workflow autonomy boundaries."""
        try:
            from core.workflow_runtime import get_autonomy_limits
            return _ok(get_autonomy_limits())
        except Exception as e:
            return _err(str(e)[:200])

    # ── Business Pipeline ────────────────────────────────────────

    @router.get("/business/dashboard")
    def business_dashboard():
        """Full business pipeline dashboard."""
        try:
            from core.business_pipeline import (
                get_lead_tracker, get_content_pipeline,
                get_budget_tracker, get_business_dashboard,
            )
            return _ok(get_business_dashboard(
                get_lead_tracker(), get_content_pipeline(), get_budget_tracker(),
            ))
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/business/leads")
    def list_leads(stage: str = "", tag: str = ""):
        """List leads with optional filters."""
        try:
            from core.business_pipeline import get_lead_tracker
            return _ok(get_lead_tracker().list_leads(stage=stage, tag=tag))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/business/leads")
    def add_lead(body: dict = Body(default={})):
        """Add a new lead."""
        try:
            from core.business_pipeline import get_lead_tracker
            lead = get_lead_tracker().add_lead(
                name=body.get("name", ""),
                source=body.get("source", ""),
                value_estimate=body.get("value_estimate", 0),
                tags=body.get("tags", []),
                contact_info=body.get("contact_info", {}),
                notes=body.get("notes", ""),
                objective_id=body.get("objective_id", ""),
            )
            return _ok(lead.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/business/leads/{lead_id}/advance")
    def advance_lead(lead_id: str, body: dict = Body(default={})):
        """Advance a lead to next pipeline stage."""
        try:
            from core.business_pipeline import get_lead_tracker
            lead = get_lead_tracker().advance_lead(
                lead_id, body.get("stage", ""), body.get("note", ""),
            )
            return _ok(lead.to_dict()) if lead else _err("lead not found or invalid stage")
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/business/content")
    def list_content(stage: str = "", content_type: str = ""):
        """List content items."""
        try:
            from core.business_pipeline import get_content_pipeline
            return _ok(get_content_pipeline().list_items(stage=stage, content_type=content_type))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/business/content")
    def create_content(body: dict = Body(default={})):
        """Create a content item."""
        try:
            from core.business_pipeline import get_content_pipeline
            item = get_content_pipeline().create(
                title=body.get("title", ""),
                content_type=body.get("content_type", "article"),
                body=body.get("body", ""),
                tags=body.get("tags", []),
                lead_id=body.get("lead_id", ""),
                objective_id=body.get("objective_id", ""),
            )
            return _ok(item.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/business/content/{content_id}/advance")
    def advance_content(content_id: str, body: dict = Body(default={})):
        """Advance content to next stage."""
        try:
            from core.business_pipeline import get_content_pipeline
            item = get_content_pipeline().advance(content_id, body.get("stage", ""))
            return _ok(item.to_dict()) if item else _err("not found or invalid stage")
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/business/budget")
    def budget_summary(objective_id: str = "", days: int = 30):
        """Get budget summary."""
        try:
            from core.business_pipeline import get_budget_tracker
            return _ok(get_budget_tracker().get_summary(
                objective_id=objective_id, days=days,
            ))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/business/budget")
    def record_budget(body: dict = Body(default={})):
        """Record a budget entry."""
        try:
            from core.business_pipeline import get_budget_tracker
            entry = get_budget_tracker().record(
                category=body.get("category", ""),
                amount=body.get("amount", 0),
                description=body.get("description", ""),
                objective_id=body.get("objective_id", ""),
                lead_id=body.get("lead_id", ""),
                mission_id=body.get("mission_id", ""),
                tags=body.get("tags", []),
            )
            return _ok(entry.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/summary")
    def operating_summary():
        """Complete operating intelligence summary."""
        try:
            from core.operating_primitives import get_operating_summary
            return _ok(get_operating_summary())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/recommendations")
    def operating_recommendations():
        """Get focus recommendations."""
        try:
            from core.operating_primitives import recommend_focus
            return _ok([r.to_dict() for r in recommend_focus()])
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/operating/playbooks")
    def operating_playbooks():
        """Get reusable playbook suggestions."""
        try:
            from core.operating_primitives import suggest_playbooks
            return _ok(suggest_playbooks())
        except Exception as e:
            return _err(str(e)[:200])

    # ── Governance ───────────────────────────────────────────

    @router.get("/governance/dashboard")
    def governance_dashboard():
        """Complete governance and safety dashboard."""
        try:
            from core.governance import get_governance_dashboard
            return _ok(get_governance_dashboard())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/governance/rate-limits")
    def governance_rate_limits():
        """Current rate limit status."""
        try:
            from core.governance import get_rate_limit_status
            return _ok(get_rate_limit_status())
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/governance/classify-danger")
    def classify_danger_endpoint(body: dict = Body(default={})):
        """Classify danger level of an action."""
        try:
            from core.governance import classify_danger
            return _ok(classify_danger(
                body.get("connector", ""),
                body.get("action", ""),
                body.get("goal", ""),
            ))
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/governance/persistence")
    def governance_persistence():
        """Validate all persistence files."""
        try:
            from core.governance import validate_all_persistence
            return _ok(validate_all_persistence())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/governance/mission-audit")
    def mission_audit():
        """Mission audit trail."""
        try:
            from core.governance import get_mission_audit
            return _ok(get_mission_audit())
        except Exception as e:
            return _err(str(e)[:200])

    # ── Multi-Business Domains ───────────────────────────────

    @router.get("/domains")
    def list_domains(status: str = ""):
        """List business domains."""
        try:
            from core.governance import get_domain_manager
            return _ok(get_domain_manager().list_domains(status))
        except Exception as e:
            return _err(str(e)[:200])

    @router.post("/domains")
    def create_domain(body: dict = Body(default={})):
        """Create a business domain."""
        try:
            from core.governance import get_domain_manager
            domain = get_domain_manager().create_domain(
                name=body.get("name", ""),
                description=body.get("description", ""),
                lead_tags=body.get("lead_tags", []),
                slot_allocation=body.get("slot_allocation", 0.2),
            )
            return _ok(domain.to_dict())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/domains/portfolio")
    def domain_portfolio():
        """Full multi-business portfolio dashboard."""
        try:
            from core.governance import get_domain_manager
            return _ok(get_domain_manager().get_portfolio_dashboard())
        except Exception as e:
            return _err(str(e)[:200])

    @router.get("/domains/recommendations")
    def domain_recommendations():
        """Slot allocation recommendations."""
        try:
            from core.governance import get_domain_manager
            return _ok(get_domain_manager().recommend_slot_allocation())
        except Exception as e:
            return _err(str(e)[:200])
