"""
JARVIS MAX — Cognitive API Routes
=====================================
REST API for all 8 cognitive modules via CognitiveBridge.

GET  /api/v3/cognitive/stats         — Full cognitive system overview
POST /api/v3/cognitive/analyze       — Pre-mission analysis (MetaCognition)
POST /api/v3/cognitive/score         — Score a routing decision
GET  /api/v3/cognitive/reputation    — Agent reputation leaderboard
GET  /api/v3/cognitive/reputation/{agent_id} — Single agent reputation
GET  /api/v3/cognitive/graph/stats   — Memory graph stats
GET  /api/v3/cognitive/graph/subgraph/{node_id} — Subgraph around a node
GET  /api/v3/cognitive/traces        — Recent learning traces
GET  /api/v3/cognitive/capabilities  — Capability graph listing
POST /api/v3/cognitive/capabilities/find — Find agents for task
GET  /api/v3/cognitive/playbooks     — List playbooks
POST /api/v3/cognitive/playbooks/start — Start a playbook execution
GET  /api/v3/cognitive/marketplace   — Search marketplace
GET  /api/v3/cognitive/confidence    — Calibration report
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/cognitive", tags=["cognitive"])


# ── Request models ──

class AnalyzeRequest(BaseModel):
    goal: str = ""
    agent_id: str = ""
    context: dict = Field(default_factory=dict)

class ScoreRequest(BaseModel):
    decision_type: str = "agent"  # agent | model | approval
    chosen: str = ""
    alternatives: List[str] = Field(default_factory=list)
    context: str = ""
    risk_level: str = "low"
    agent_id: str = ""
    budget: str = ""

class FindAgentsRequest(BaseModel):
    keywords: List[str] = Field(default_factory=list)

class StartPlaybookRequest(BaseModel):
    playbook_id: str = ""
    mission_id: str = ""
    params: dict = Field(default_factory=dict)


def _get_bridge():
    try:
        from core.cognitive_bridge import get_bridge
        return get_bridge()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cognitive bridge unavailable: {e}")


def _check_auth(authorization: str | None) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")


# ── Routes ──

@router.get("/stats")
async def cognitive_stats(authorization: str | None = Header(None)):
    _check_auth(authorization)
    return _get_bridge().stats()


@router.post("/analyze")
async def analyze_task(req: AnalyzeRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    result = bridge.pre_mission(
        goal=req.goal, agent_id=req.agent_id, context=req.context or None
    )
    return result


@router.post("/score")
async def score_decision(req: ScoreRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    return bridge.score_decision(
        decision_type=req.decision_type,
        chosen=req.chosen,
        alternatives=req.alternatives,
        context=req.context,
        risk_level=req.risk_level,
        agent_id=req.agent_id,
        budget=req.budget,
    )


# ── Reputation ──

@router.get("/reputation")
async def reputation_leaderboard(authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    rep = bridge.reputation
    if not rep:
        return {"agents": [], "status": "unavailable"}
    return {"agents": rep.get_all()}


@router.get("/reputation/{agent_id}")
async def agent_reputation(agent_id: str, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    rep = bridge.reputation
    if not rep:
        raise HTTPException(status_code=503, detail="Reputation unavailable")
    record = rep.get_record(agent_id)
    if not record:
        return {"agent_id": agent_id, "reputation_score": 0.5, "status": "no_data"}
    return record


# ── Memory Graph ──

@router.get("/graph/stats")
async def graph_stats(authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    g = bridge.memory_graph
    if not g:
        return {"status": "unavailable"}
    return g.stats()


@router.get("/graph/subgraph/{node_id}")
async def graph_subgraph(node_id: str, depth: int = 2, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    g = bridge.memory_graph
    if not g:
        raise HTTPException(status_code=503, detail="Memory graph unavailable")
    sub = g.subgraph(node_id, depth=min(depth, 5))
    return sub


# ── Learning Traces ──

@router.get("/traces")
async def learning_traces(limit: int = 50, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    lt = bridge.learning_traces
    if not lt:
        return {"traces": [], "status": "unavailable"}
    all_traces = lt.get_all()  # Already returns list of dicts
    return {"traces": all_traces[-limit:], "total": len(all_traces)}


# ── Capabilities ──

@router.get("/capabilities")
async def list_capabilities(authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    cg = bridge.capability_graph
    if not cg:
        return {"capabilities": [], "status": "unavailable"}
    return {"capabilities": cg.list_all(), "stats": cg.stats()}


@router.post("/capabilities/find")
async def find_agents_for_task(req: FindAgentsRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    cg = bridge.capability_graph
    if not cg:
        return {"agents": [], "status": "unavailable"}
    return {"agents": cg.find_agents_for_task(req.keywords)}


# ── Playbooks ──

@router.get("/playbooks")
async def list_playbooks(
    category: str = "", query: str = "",
    authorization: str | None = Header(None),
):
    _check_auth(authorization)
    bridge = _get_bridge()
    results = bridge.find_playbook(category=category, query=query)
    return {"playbooks": results}


@router.post("/playbooks/start")
async def start_playbook(req: StartPlaybookRequest, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    result = bridge.start_playbook(req.playbook_id, req.mission_id, req.params)
    if not result:
        raise HTTPException(status_code=404, detail=f"Playbook {req.playbook_id} not found")
    return result


# ── Marketplace ──

@router.get("/marketplace")
async def marketplace_search(
    query: str = "", type: str = "",
    authorization: str | None = Header(None),
):
    _check_auth(authorization)
    bridge = _get_bridge()
    results = bridge.marketplace_search(query=query, type=type)
    return {"items": results}


# ── Confidence ──

@router.get("/confidence")
async def confidence_report(authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    conf = bridge.confidence
    if not conf:
        return {"status": "unavailable"}
    return conf.calibration_report()


@router.get("/confidence/history")
async def confidence_history(limit: int = 50, authorization: str | None = Header(None)):
    _check_auth(authorization)
    bridge = _get_bridge()
    conf = bridge.confidence
    if not conf:
        return {"decisions": [], "status": "unavailable"}
    return {"decisions": conf.get_history(limit=limit)}
