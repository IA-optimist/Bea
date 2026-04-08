"""
JarvisMax — Opportunities API
REST endpoints for SaaS opportunity management (Phase 3)
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api._deps import require_auth, get_db
from models.opportunity import Opportunity
from business.automation.opportunity_scanner import OpportunityScanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v3/business/opportunities", tags=["opportunities"], dependencies=[Depends(require_auth)])


def _response(data=None, message: str = "ok", status: str = "success") -> dict:
    return {"status": status, "message": message, "data": data, "timestamp": time.time()}


# ═══════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════

class OpportunityResponse(BaseModel):
    """Single opportunity response"""
    id: int
    title: str
    description: str
    source: str
    url: str
    discovered_at: str
    metrics: dict
    scores: dict
    tags: List[str]
    pain_points: List[str]
    status: dict
    created_at: str
    updated_at: str


class OpportunityListResponse(BaseModel):
    """List of opportunities with pagination"""
    items: List[OpportunityResponse]
    total: int
    page: int
    page_size: int


class ScanRequest(BaseModel):
    """Trigger manual scan"""
    sources: Optional[List[str]] = Field(default=["product_hunt", "reddit", "hackernews"], 
                                         description="Sources to scan")
    min_score: Optional[float] = Field(default=70.0, ge=0.0, le=100.0,
                                       description="Minimum total score threshold")
    limit: Optional[int] = Field(default=10, ge=1, le=50,
                                 description="Max opportunities to store")


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@router.get("", response_model=dict)
async def list_opportunities(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    source: Optional[str] = Query(None, description="Filter by source"),
    min_score: Optional[float] = Query(None, ge=0.0, le=100.0, description="Min total score"),
    analyzed: Optional[bool] = Query(None, description="Filter by analyzed status"),
    sort_by: str = Query("total_score", description="Sort field: total_score, discovered_at, demand_score"),
):
    """
    List opportunities with filtering and pagination
    
    **Filters:**
    - `source`: product_hunt, reddit, hackernews, indie_hackers
    - `min_score`: Minimum total score (0-100)
    - `analyzed`: TRUE (analyzed), FALSE (not analyzed), NULL (all)
    
    **Sorting:**
    - `total_score` (default): Highest score first
    - `discovered_at`: Most recent first
    - `demand_score`: Highest demand first
    """
    try:
        query = db.query(Opportunity)
        
        # Apply filters
        if source:
            query = query.filter(Opportunity.source == source)
        if min_score is not None:
            query = query.filter(Opportunity.total_score >= min_score)
        if analyzed is not None:
            query = query.filter(Opportunity.analyzed == analyzed)
        
        # Total count
        total = query.count()
        
        # Sorting
        sort_column = {
            "total_score": desc(Opportunity.total_score),
            "discovered_at": desc(Opportunity.discovered_at),
            "demand_score": desc(Opportunity.demand_score),
        }.get(sort_by, desc(Opportunity.total_score))
        
        query = query.order_by(sort_column)
        
        # Pagination
        offset = (page - 1) * page_size
        items = query.offset(offset).limit(page_size).all()
        
        return _response(data={
            "items": [opp.to_dict() for opp in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size,
        })
    
    except Exception as e:
        logger.error(f"list_opportunities_failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{opportunity_id}", response_model=dict)
async def get_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
):
    """Get single opportunity by ID"""
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    return _response(data=opportunity.to_dict())


@router.post("/scan", response_model=dict)
async def trigger_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger manual opportunity scan (async background task)
    
    **Process:**
    1. Scan specified sources (Product Hunt, Reddit, HN)
    2. Score opportunities (demand, competition, feasibility, monetization)
    3. Filter by min_score threshold
    4. Store top N in database
    5. Send Telegram alerts for exceptional opportunities (score > 85)
    
    **Returns immediately** — scan runs in background
    """
    try:
        def _run_scan():
            scanner = OpportunityScanner()
            opportunities = []
            
            for source in request.sources:
                try:
                    if source == "product_hunt":
                        opportunities.extend(scanner.scan_product_hunt())
                    elif source == "reddit":
                        opportunities.extend(scanner.scan_reddit())
                    elif source == "hackernews":
                        opportunities.extend(scanner.scan_hackernews())
                except Exception as e:
                    logger.error(f"scan_source_failed source={source}: {e}")
            
            # Filter by score
            high_value = [opp for opp in opportunities if opp.total_score >= request.min_score]
            
            # Store top N
            stored_count = 0
            for opp_data in sorted(high_value, key=lambda x: x.total_score, reverse=True)[:request.limit]:
                # Check if exists
                existing = db.query(Opportunity).filter(Opportunity.url == opp_data.url).first()
                if existing:
                    continue
                
                opportunity = Opportunity(
                    title=opp_data.title,
                    description=opp_data.description,
                    source=opp_data.source,
                    url=opp_data.url,
                    discovered_at=opp_data.discovered_at,
                    upvotes=opp_data.upvotes,
                    comments=opp_data.comments,
                    mentions=opp_data.mentions,
                    demand_score=opp_data.demand_score,
                    competition_score=opp_data.competition_score,
                    feasibility_score=opp_data.feasibility_score,
                    monetization_score=opp_data.monetization_score,
                    total_score=opp_data.total_score,
                    tags=opp_data.tags,
                    pain_points=opp_data.pain_points,
                    raw_data=opp_data.to_dict(),
                )
                
                db.add(opportunity)
                db.commit()
                stored_count += 1
            
            logger.info(f"scan_completed: total={len(opportunities)} high_value={len(high_value)} stored={stored_count}")
        
        # Run in background
        background_tasks.add_task(_run_scan)
        
        return _response(
            message="Scan started in background",
            data={
                "sources": request.sources,
                "min_score": request.min_score,
                "limit": request.limit,
            }
        )
    
    except Exception as e:
        logger.error(f"trigger_scan_failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{opportunity_id}", response_model=dict)
async def delete_opportunity(
    opportunity_id: int,
    db: Session = Depends(get_db),
):
    """Delete opportunity by ID"""
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    db.delete(opportunity)
    db.commit()
    
    return _response(message=f"Opportunity {opportunity_id} deleted")


@router.get("/stats/summary", response_model=dict)
async def get_stats(db: Session = Depends(get_db)):
    """
    Get opportunity statistics summary
    
    **Returns:**
    - Total opportunities
    - By source breakdown
    - By score range
    - Analyzed/unanalyzed counts
    - MVP generation stats
    """
    try:
        total = db.query(Opportunity).count()
        analyzed = db.query(Opportunity).filter(Opportunity.analyzed == True).count()
        mvp_generated = db.query(Opportunity).filter(Opportunity.mvp_generated == True).count()
        deployed = db.query(Opportunity).filter(Opportunity.deployed == True).count()
        
        # By source
        sources = {}
        for source in ["product_hunt", "reddit", "hackernews", "indie_hackers"]:
            count = db.query(Opportunity).filter(Opportunity.source == source).count()
            if count > 0:
                sources[source] = count
        
        # By score range
        score_ranges = {
            "excellent": db.query(Opportunity).filter(Opportunity.total_score >= 85).count(),
            "high": db.query(Opportunity).filter(Opportunity.total_score >= 70, Opportunity.total_score < 85).count(),
            "medium": db.query(Opportunity).filter(Opportunity.total_score >= 50, Opportunity.total_score < 70).count(),
            "low": db.query(Opportunity).filter(Opportunity.total_score < 50).count(),
        }
        
        # Top opportunities
        top_opportunities = db.query(Opportunity).order_by(desc(Opportunity.total_score)).limit(5).all()
        
        return _response(data={
            "total": total,
            "analyzed": analyzed,
            "mvp_generated": mvp_generated,
            "deployed": deployed,
            "by_source": sources,
            "by_score_range": score_ranges,
            "top_opportunities": [
                {
                    "id": opp.id,
                    "title": opp.title,
                    "source": opp.source,
                    "total_score": round(opp.total_score, 2),
                    "discovered_at": opp.discovered_at.isoformat(),
                }
                for opp in top_opportunities
            ],
        })
    
    except Exception as e:
        logger.error(f"get_stats_failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
