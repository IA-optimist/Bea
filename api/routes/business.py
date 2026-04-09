"""
Phase 7.3: Business Performance & Skills API

Endpoints for portfolio analytics, performance tracking, and skill library.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from api._deps import get_db, _check_auth
from core.business.portfolio_manager import PortfolioManager
from core.cognition.lifelong_learning import LifelongLearningEngine

router = APIRouter(prefix="/api/v3/business", tags=["business"])


# ── Response Models ──────────────────────────────────────────────────

class PortfolioSummaryResponse(BaseModel):
    total_opportunities: int
    total_mvps: int
    deployed_mvps: int
    active_projects: int
    estimated_monthly_revenue: float
    currency: str
    top_opportunities: List[Dict[str, Any]]
    generated_at: str


class ProjectMetricsResponse(BaseModel):
    project_id: int
    opportunities: Dict[str, int]
    mvps: Dict[str, int]
    estimated_monthly_revenue: float
    currency: str


class SkillResponse(BaseModel):
    skill_id: str
    name: str
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    validated: bool
    uses: int = 0
    code: Optional[str] = None
    tags: List[str] = []


class SkillsLibraryResponse(BaseModel):
    skills: List[SkillResponse]
    total_count: int
    validated_count: int


class SkillSuggestionRequest(BaseModel):
    goal: str
    limit: int = Field(default=3, ge=1, le=10)


class SkillSuggestionResponse(BaseModel):
    suggestions: List[Dict[str, Any]]
    goal: str


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/performance", response_model=PortfolioSummaryResponse)
async def get_portfolio_performance(
    db: Session = Depends(get_db),
    _auth = Depends(_check_auth)
):
    """
    Get global portfolio performance metrics.
    
    Returns statistics across all projects:
    - Total opportunities/MVPs
    - Deployed MVPs
    - Estimated revenue
    - Top opportunities
    """
    manager = PortfolioManager(db)
    summary = manager.get_portfolio_summary()
    return summary


@router.get("/performance/projects/{project_id}", response_model=ProjectMetricsResponse)
async def get_project_performance(
    project_id: int,
    db: Session = Depends(get_db),
    _auth = Depends(_check_auth)
):
    """Get performance metrics for a specific project."""
    manager = PortfolioManager(db)
    metrics = manager.get_project_metrics(project_id)
    return metrics


@router.get("/skills", response_model=SkillsLibraryResponse)
async def get_skills_library(
    validated: Optional[bool] = None,
    min_success_rate: Optional[float] = None,
    limit: int = 50,
    _auth = Depends(_check_auth)
):
    """
    Get learned business skills library.
    
    Query parameters:
    - validated: Filter by validation status
    - min_success_rate: Minimum success rate (0.0-1.0)
    - limit: Max skills to return
    """
    learning = LifelongLearningEngine()
    
    # Get all skills
    all_skills_data = learning.get_all_skills()
    
    # Parse skills
    skills = []
    for skill_data in all_skills_data:
        success = skill_data.get("success_count", 0)
        failure = skill_data.get("failure_count", 0)
        total = success + failure
        success_rate = success / total if total > 0 else 0.0
        
        # Apply filters
        if validated is not None and skill_data.get("is_validated") != validated:
            continue
        if min_success_rate is not None and success_rate < min_success_rate:
            continue
        
        skills.append(SkillResponse(
            skill_id=skill_data["skill_id"],
            name=skill_data["name"],
            success_count=success,
            failure_count=failure,
            success_rate=success_rate,
            confidence=skill_data.get("confidence", 0.5),
            validated=skill_data.get("is_validated", False),
            uses=total,
            code=skill_data.get("code"),
            tags=skill_data.get("tags", []),
        ))
    
    # Sort by success rate
    skills.sort(key=lambda s: s.success_rate, reverse=True)
    
    # Limit
    skills = skills[:limit]
    
    validated_count = sum(1 for s in skills if s.validated)
    
    return SkillsLibraryResponse(
        skills=skills,
        total_count=len(skills),
        validated_count=validated_count,
    )


@router.post("/skills/suggest", response_model=SkillSuggestionResponse)
async def suggest_skills(
    req: SkillSuggestionRequest,
    _auth = Depends(_check_auth)
):
    """
    Suggest relevant skills for a given goal.
    
    Uses semantic similarity to find skills that match the goal.
    """
    learning = LifelongLearningEngine()
    
    suggestions = await learning.suggest_skills_for_goal(
        goal=req.goal,
        limit=req.limit
    )
    
    return SkillSuggestionResponse(
        suggestions=suggestions,
        goal=req.goal,
    )


@router.get("/patterns")
async def get_cross_project_patterns(
    db: Session = Depends(get_db),
    _auth = Depends(_check_auth)
):
    """
    Get patterns across all projects.
    
    Returns:
    - Popular tech stacks
    - Popular categories
    - Average revenue by category
    - Total portfolio revenue
    """
    manager = PortfolioManager(db)
    patterns = manager.get_cross_project_patterns()
    return patterns
