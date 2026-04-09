"""
JarvisMax Conversational Chat API (Phase 5.3 - Clean Rewrite)
==============================================================
Natural conversation endpoint with AGI cognition.

POST /api/v3/chat - Conversational interaction with context
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Annotated

from api._deps import _check_auth
from core.cognition.orchestrator import CognitionOrchestrator
from langchain_openai import ChatOpenAI
import os

router = APIRouter(prefix="/api/v3", tags=["chat"])


# ── Request/Response Models ──

class ChatMessage(BaseModel):
    """Single chat message."""
    role: str
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    """Chat request with context."""
    message: str = Field(..., min_length=1)
    project_id: int = Field(default=1)
    conversation_history: List[ChatMessage] = Field(default_factory=list)
    enable_tot: bool = Field(default=True)
    enable_self_correction: bool = Field(default=True)


class ChatResponse(BaseModel):
    """Chat response with cognition metadata."""
    response: str
    confidence_score: float = 0.0
    reasoning_used: str = "direct"
    project_id: int = 1
    timestamp: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Complexity Detection ──

def detect_query_complexity(message: str) -> str:
    """Detect if query is simple or complex."""
    message_lower = message.lower()
    
    complex_keywords = [
        "compare", "versus", "vs", "difference between",
        "plan", "strategy", "approach", "how should i",
        "what if", "alternatives", "options",
        "step by step", "guide me", "help me decide",
        "pros and cons", "trade-offs"
    ]
    
    for keyword in complex_keywords:
        if keyword in message_lower:
            return "complex"
    
    if message.count("?") >= 2:
        return "complex"
    
    if len(message.split()) > 50:
        return "complex"
    
    return "simple"


# ── Orchestrator Singleton ──

_orchestrator: Optional[CognitionOrchestrator] = None


def _get_orchestrator() -> CognitionOrchestrator:
    """Get or create CognitionOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        llm_client = ChatOpenAI(
            model="anthropic/claude-sonnet-4",
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
            temperature=0.7,
        )
        _orchestrator = CognitionOrchestrator(llm_client)
    return _orchestrator


# ── Chat Endpoint ──

@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Conversational chat with AGI cognition."""
    _check_auth(x_jarvis_token, authorization)
    
    orchestrator = _get_orchestrator()
    
    # Detect complexity
    complexity = detect_query_complexity(req.message)
    use_tot = req.enable_tot and complexity == "complex"
    
    # Build mission dict
    mission = {
        "mission_id": f"chat-{datetime.utcnow().timestamp()}",
        "goal": req.message,
        "context": {
            "conversation_history": [
                {"role": msg.role, "content": msg.content}
                for msg in req.conversation_history
            ],
            "complexity": complexity,
        }
    }
    
    try:
        # Execute with project context
            mission,
            project_id=req.project_id,
            enable_tot=use_tot,
            enable_confidence=True,
            enable_learning=True
        )
        
        response_text = result.get("result", "")
        confidence = result.get("confidence_score", 0.5)
        reasoning = "tree-of-thought" if use_tot else "direct"
        
        # Self-correction if confidence too low
        if req.enable_self_correction and confidence < 0.6:
            mission["context"]["previous_attempt"] = response_text
            mission["context"]["previous_confidence"] = confidence
            
            corrected_result = await orchestrator.execute_with_project_context(
                mission,
                project_id=req.project_id,
                enable_tot=True,
                enable_confidence=True,
                enable_learning=True
            )
            
            corrected_confidence = corrected_result.get("confidence_score", 0.5)
            
            if corrected_confidence > confidence:
                response_text = corrected_result.get("result", response_text)
                confidence = corrected_confidence
                reasoning = "corrected"
        
        return ChatResponse(
            response=response_text,
            confidence_score=confidence,
            reasoning_used=reasoning,
            project_id=req.project_id,
            timestamp=datetime.utcnow().isoformat(),
            metadata={
                "complexity": complexity,
                "tot_used": use_tot or reasoning == "corrected",
                "self_corrected": reasoning == "corrected",
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@router.get("/chat/projects/{project_id}/performance")
async def get_project_performance(
    project_id: int,
    x_jarvis_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Get cognitive performance metrics for a project."""
    _check_auth(x_jarvis_token, authorization)
    
    orchestrator = _get_orchestrator()
    perf_summary = orchestrator.get_project_performance()
    
    project_data = next(
        (p for p in perf_summary["projects"] if p["id"] == project_id),
        None
    )
    
    if not project_data:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    return {
        "project_id": project_id,
        "project_name": project_data["name"],
        "missions_total": project_data["missions"],
        "success_rate": project_data["success_rate"],
        "avg_confidence": project_data["avg_confidence"],
        "skills_learned": project_data["skills"],
        "global_summary": {
            "total_projects": perf_summary["total_projects"],
            "global_success_rate": perf_summary["success_rate"],
            "global_avg_confidence": perf_summary["avg_confidence"],
        }
    }
