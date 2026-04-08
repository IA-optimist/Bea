"""
JarvisMax — Opportunities API
REST endpoints for SaaS opportunity management (Phase 3)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.auth import get_current_user
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


# ═══════════════════════════════════════════════════════════════════
# P3.2: FEASIBILITY ANALYSIS
# ═══════════════════════════════════════════════════════════════════

from models.opportunity_analysis import OpportunityAnalysis
from core.business.feasibility_analyzer import FeasibilityAnalyzer


@router.post("/{opportunity_id}/analyze", response_model=dict)
async def analyze_feasibility(
    opportunity_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    project_id: int = Query(1, description="JarvisMax project ID"),
):
    """
    Analyze technical feasibility of an opportunity (cognition-powered)
    
    **Process:**
    1. Retrieve opportunity from database
    2. Run FeasibilityAnalyzer (CognitionOrchestrator + Tree-of-Thought)
    3. Store analysis result in opportunity_analyses table
    4. Update opportunity.analyzed = TRUE
    
    **Returns immediately** — analysis runs in background (4-8 minutes)
    
    **Cognition confidence threshold:** 0.8 (high confidence required)
    
    **Example response:**
    ```json
    {
      "status": "success",
      "message": "Analysis started",
      "data": {
        "opportunity_id": 1,
        "mission_id": "abc123",
        "estimated_duration": "4-8 minutes"
      }
    }
    ```
    
    **After completion, GET /api/v3/business/opportunities/{id}/analysis to view results.**
    """
    # Validate opportunity exists
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # Check if already analyzed
    existing = db.query(OpportunityAnalysis).filter(
        OpportunityAnalysis.opportunity_id == opportunity_id
    ).first()
    
    if existing:
        return _response(
            message="Opportunity already analyzed",
            data={
                "opportunity_id": opportunity_id,
                "analysis_id": existing.id,
                "analyzed_at": existing.analyzed_at.isoformat(),
                "recommendation": existing.recommendation,
            }
        )
    
    # Background analysis task
    async def _run_analysis():
        try:
            analyzer = FeasibilityAnalyzer()
            
            logger.info(f"Starting feasibility analysis for opportunity {opportunity_id}")
            
            # Run analysis (cognition-powered, may take 4-8 minutes)
            analysis_result = await analyzer.analyze(opportunity, project_id=project_id)
            
            # Store in database
            analysis = OpportunityAnalysis(
                opportunity_id=opportunity_id,
                analyzed_at=datetime.utcnow(),
                analysis_duration_seconds=analysis_result.get("duration_seconds"),
                mission_id=analysis_result.get("mission_id"),
                confidence_score=analysis_result.get("confidence_score"),
                cognition_reasoning=analysis_result.get("cognition_reasoning"),
                tech_stack=analysis_result.get("tech_stack"),
                dependencies=analysis_result.get("dependencies"),
                complexity_score=analysis_result.get("complexity_score"),
                estimated_hours=analysis_result.get("estimated_hours"),
                mvp_features=analysis_result.get("mvp_features"),
                nice_to_have_features=analysis_result.get("nice_to_have_features"),
                out_of_scope=analysis_result.get("out_of_scope"),
                technical_risks=analysis_result.get("technical_risks"),
                mitigation_strategies=analysis_result.get("mitigation_strategies"),
                recommendation=analysis_result.get("recommendation"),
                reasoning=analysis_result.get("reasoning"),
                market_fit_score=analysis_result.get("market_fit_score"),
                full_analysis=analysis_result.get("full_analysis"),
                raw_output=analysis_result,
            )
            
            db.add(analysis)
            
            # Update opportunity.analyzed = TRUE
            opportunity.analyzed = True
            
            db.commit()
            db.refresh(analysis)
            
            logger.info(
                f"feasibility_analysis_stored "
                f"opportunity_id={opportunity_id} "
                f"analysis_id={analysis.id} "
                f"recommendation={analysis.recommendation} "
                f"confidence={analysis.confidence_score:.3f}"
            )
        
        except Exception as e:
            logger.error(f"feasibility_analysis_background_failed opportunity_id={opportunity_id}: {e}", exc_info=True)
            db.rollback()
    
    # Run in background
    background_tasks.add_task(_run_analysis)
    
    return _response(
        message="Feasibility analysis started",
        data={
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "estimated_duration": "4-8 minutes",
            "status_endpoint": f"/api/v3/business/opportunities/{opportunity_id}/analysis",
        }
    )


@router.get("/{opportunity_id}/analysis", response_model=dict)
async def get_analysis(
    opportunity_id: int,
    db: Session = Depends(get_db),
):
    """
    Get feasibility analysis result for an opportunity
    
    **Returns:**
    - 404: Opportunity not found
    - 202: Analysis in progress (not ready yet)
    - 200: Analysis complete (full result)
    """
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    analysis = db.query(OpportunityAnalysis).filter(
        OpportunityAnalysis.opportunity_id == opportunity_id
    ).first()
    
    if not analysis:
        # Check if analysis is in progress (opportunity.analyzed = FALSE)
        if not opportunity.analyzed:
            raise HTTPException(
                status_code=202,
                detail="Analysis in progress or not started. Please try again in 4-8 minutes."
            )
        else:
            raise HTTPException(
                status_code=404,
                detail="Analysis not found (may have been deleted)"
            )
    
    return _response(data=analysis.to_dict())


@router.delete("/{opportunity_id}/analysis", response_model=dict)
async def delete_analysis(
    opportunity_id: int,
    db: Session = Depends(get_db),
):
    """Delete feasibility analysis (allows re-analysis)"""
    analysis = db.query(OpportunityAnalysis).filter(
        OpportunityAnalysis.opportunity_id == opportunity_id
    ).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Also reset opportunity.analyzed = FALSE
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if opportunity:
        opportunity.analyzed = False
    
    db.delete(analysis)
    db.commit()
    
    return _response(message=f"Analysis deleted (opportunity {opportunity_id} can be re-analyzed)")


# ═══════════════════════════════════════════════════════════════════
# P3.3 — MVP GENERATION
# ═══════════════════════════════════════════════════════════════════

@router.post("/{opportunity_id}/generate-mvp")
async def generate_mvp(
    opportunity_id: int,
    background_tasks: BackgroundTasks,
    project_id: int = 1,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Generate MVP codebase from feasibility analysis (P3.3).
    
    Args:
        opportunity_id: Opportunity ID
        project_id: JarvisMax project ID (default: 1)
        db: Database session
    
    Returns:
        Dict with generation status:
        {
            "status": "success",
            "message": "MVP generation started",
            "data": {
                "opportunity_id": 1,
                "project_id": 1,
                "estimated_duration": "2-4 minutes",
                "status_endpoint": "/api/v3/business/opportunities/1/mvp"
            }
        }
    
    Errors:
        - 404: Opportunity not found
        - 400: Analysis not found or not approved
    """
    from core.business.mvp_generator import MVPGenerator
    from models.opportunity_analysis import OpportunityAnalysis
    
    # Validate opportunity
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # Validate analysis exists and is approved
    analysis = db.query(OpportunityAnalysis).filter(
        OpportunityAnalysis.opportunity_id == opportunity_id
    ).first()
    
    if not analysis:
        raise HTTPException(
            status_code=400,
            detail=f"No feasibility analysis found for opportunity {opportunity_id}. Run POST /opportunities/{opportunity_id}/analyze first."
        )
    
    if not analysis.approved:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis for opportunity {opportunity_id} is not approved. Set approved=true before generating MVP."
        )
    
    # Check if already generated
    if opportunity.mvp_generated:
        logger.warning(f"mvp_already_generated opportunity_id={opportunity_id}")
        return {
            "status": "success",
            "message": "MVP already generated",
            "data": {
                "opportunity_id": opportunity_id,
                "project_id": project_id,
                "status_endpoint": f"/api/v3/business/opportunities/{opportunity_id}/mvp",
            }
        }
    
    # Run MVP generation in background
    async def _run_generation():
        try:
            logger.info(f"background_mvp_generation_started opportunity_id={opportunity_id}")
            
            generator = MVPGenerator()
            result = generator.generate(opportunity, analysis)
            
            if result["success"]:
                # Update opportunity
                opportunity.mvp_generated = True
                db.commit()
                
                logger.info(
                    f"background_mvp_generation_completed "
                    f"opportunity_id={opportunity_id} "
                    f"files_created={result['files_created']} "
                    f"output_dir={result['output_dir']}"
                )
            else:
                logger.error(
                    f"background_mvp_generation_failed "
                    f"opportunity_id={opportunity_id} "
                    f"error={result.get('error')}"
                )
        
        except Exception as e:
            logger.error(f"background_mvp_generation_exception opportunity_id={opportunity_id}: {e}", exc_info=True)
            db.rollback()
    
    # Add background task
    background_tasks.add_task(_run_generation)
    
    return {
        "status": "success",
        "message": "MVP generation started",
        "data": {
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "estimated_duration": "2-4 minutes",
            "status_endpoint": f"/api/v3/business/opportunities/{opportunity_id}/mvp",
        }
    }


@router.get("/{opportunity_id}/mvp")
async def get_mvp_status(
    opportunity_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get MVP generation status (P3.3).
    
    Args:
        opportunity_id: Opportunity ID
        db: Database session
    
    Returns:
        Dict with MVP status:
        {
            "status": "success",
            "data": {
                "opportunity_id": 1,
                "mvp_generated": true,
                "output_dir": "/tmp/jarvismax_mvp/ai-powered-code-review-tool",
                "project_slug": "ai-powered-code-review-tool",
                "files_created": 8
            }
        }
    
    Errors:
        - 404: Opportunity not found
        - 202: MVP generation in progress
    """
    # Validate opportunity
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # Check if generated
    if not opportunity.mvp_generated:
        raise HTTPException(
            status_code=202,
            detail="MVP generation in progress. Please try again in 2-4 minutes."
        )
    
    # Get analysis for project slug
    from models.opportunity_analysis import OpportunityAnalysis
    analysis = db.query(OpportunityAnalysis).filter(
        OpportunityAnalysis.opportunity_id == opportunity_id
    ).first()
    
    # Calculate output dir
    from core.business.mvp_generator import MVPGenerator
    generator = MVPGenerator()
    project_slug = generator._slugify(opportunity.title)
    output_dir = generator.workspace_dir / project_slug
    
    return {
        "status": "success",
        "data": {
            "opportunity_id": opportunity_id,
            "mvp_generated": True,
            "output_dir": str(output_dir),
            "project_slug": project_slug,
            "files_created": 8,  # Static (backend, frontend, docker, deployment, README, gitignore)
        }
    }


# ========================================
# P3.4 — DEPLOYMENT ENDPOINTS
# ========================================

@router.post("/{opportunity_id}/deploy", status_code=202)
async def deploy_mvp(
    opportunity_id: int,
    background_tasks: BackgroundTasks,
    project_id: int = Query(1, description="JarvisMax project ID"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Deploy generated MVP to VPS with GitHub + Docker + Caddy.
    
    Steps:
    1. Validate: opportunity + analysis + mvp_generated = TRUE
    2. GitHub: Create repo + push code
    3. VPS: Clone repo + docker-compose up
    4. Caddy: Configure reverse proxy
    5. DB: Create deployment record
    
    Returns 202 Accepted immediately, runs deployment in background.
    
    Check status: GET /api/v3/business/opportunities/{id}/deployment
    """
    from models.opportunity import Opportunity
    from models.opportunity_analysis import OpportunityAnalysis
    from models.opportunity_deployment import OpportunityDeployment
    from core.business.github_automation import GitHubAutomation
    from core.business.deploy_manager import DeployManager
    import time
    
    # 1. Validate opportunity
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # 2. Validate analysis exists
    analysis = (
        db.query(OpportunityAnalysis)
        .filter(OpportunityAnalysis.opportunity_id == opportunity_id)
        .order_by(OpportunityAnalysis.created_at.desc())
        .first()
    )
    if not analysis:
        raise HTTPException(
            status_code=400,
            detail=f"No analysis found for opportunity {opportunity_id}. Run analysis first."
        )
    
    # 3. Validate MVP generated
    if not opportunity.mvp_generated:
        raise HTTPException(
            status_code=400,
            detail=f"MVP not generated for opportunity {opportunity_id}. Generate MVP first."
        )
    
    # 4. Check if already deployed
    existing = db.query(OpportunityDeployment).filter(
        OpportunityDeployment.opportunity_id == opportunity_id,
        OpportunityDeployment.status.in_(["deploying", "live"])
    ).first()
    
    if existing:
        return {
            "status": "already_deployed",
            "message": f"MVP already deployed: {existing.url}",
            "data": existing.to_dict(),
        }
    
    # 5. Start background deployment
    logger.info(f"background_deployment_started opportunity_id={opportunity_id} project_id={project_id}")
    
    async def _run_deployment():
        """Background deployment task"""
        start_time = time.time()
        
        try:
            # Get MVP directory (from mvp_generator output)
            from core.business.mvp_generator import MVPGenerator
            generator = MVPGenerator()
            project_slug = generator._slugify(opportunity.title)
            mvp_dir = f"/tmp/jarvismax_mvp/{project_slug}"
            
            # GitHub automation
            logger.info(f"deploying_to_github opportunity_id={opportunity_id}")
            github = GitHubAutomation()
            github_result = github.create_and_push(opportunity, mvp_dir)
            
            if not github_result["success"]:
                logger.error(f"github_automation_failed opportunity_id={opportunity_id}: {github_result.get('message')}")
                return
            
            logger.info(f"github_push_completed opportunity_id={opportunity_id} repo={github_result['repo_name']}")
            
            # VPS deployment
            logger.info(f"deploying_to_vps opportunity_id={opportunity_id}")
            deployer = DeployManager()
            deploy_result = deployer.deploy(opportunity, github_result["repo_url"], project_slug)
            
            if not deploy_result["success"]:
                logger.error(f"vps_deployment_failed opportunity_id={opportunity_id}: {deploy_result.get('message')}")
                return
            
            logger.info(f"vps_deployment_completed opportunity_id={opportunity_id} url={deploy_result['url']}")
            
            # Create deployment record
            duration = int(time.time() - start_time)
            
            deployment = OpportunityDeployment(
                opportunity_id=opportunity_id,
                repo_name=github_result["repo_name"],
                repo_url=github_result["repo_url"],
                clone_url=github_result.get("clone_url"),
                html_url=github_result.get("html_url"),
                deploy_path=deploy_result["deploy_path"],
                subdomain=deploy_result["subdomain"],
                url=deploy_result["url"],
                status="live",
                deploy_duration_seconds=duration,
            )
            
            db.add(deployment)
            opportunity.deployed = True
            db.commit()
            
            logger.info(
                f"background_deployment_completed "
                f"opportunity_id={opportunity_id} "
                f"url={deploy_result['url']} "
                f"duration={duration}s"
            )
        
        except Exception as e:
            logger.error(f"background_deployment_failed opportunity_id={opportunity_id}: {e}", exc_info=True)
            db.rollback()
    
    background_tasks.add_task(_run_deployment)
    
    return {
        "status": "success",
        "message": "Deployment started",
        "data": {
            "opportunity_id": opportunity_id,
            "project_id": project_id,
            "estimated_duration": "5-10 minutes",
            "status_endpoint": f"/api/v3/business/opportunities/{opportunity_id}/deployment",
        },
    }


@router.get("/{opportunity_id}/deployment")
async def get_deployment_status(
    opportunity_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get deployment status for an opportunity.
    
    Returns 200 if deployed (live, down, or removed)
    Returns 202 if currently deploying
    Returns 404 if never deployed
    """
    from models.opportunity import Opportunity
    from models.opportunity_deployment import OpportunityDeployment
    
    # Check opportunity exists
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # Get latest deployment
    deployment = (
        db.query(OpportunityDeployment)
        .filter(OpportunityDeployment.opportunity_id == opportunity_id)
        .order_by(OpportunityDeployment.deployed_at.desc())
        .first()
    )
    
    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"No deployment found for opportunity {opportunity_id}"
        )
    
    # Return status
    if deployment.status == "deploying":
        return JSONResponse(
            status_code=202,
            content={
                "status": 202,
                "detail": "Deployment in progress. Please try again in 5-10 minutes.",
                "data": deployment.to_dict(),
            }
        )
    
    return {
        "status": "success",
        "data": deployment.to_dict(),
    }


@router.delete("/{opportunity_id}/deployment")
async def undeploy_mvp(
    opportunity_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Remove deployment from VPS.
    
    Steps:
    1. Stop Docker containers
    2. Remove deployment directory
    3. Remove Caddy config
    4. Update deployment status to 'removed'
    """
    from models.opportunity import Opportunity
    from models.opportunity_deployment import OpportunityDeployment
    from core.business.deploy_manager import DeployManager
    from datetime import datetime
    
    # Check opportunity exists
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    
    # Get active deployment
    deployment = (
        db.query(OpportunityDeployment)
        .filter(
            OpportunityDeployment.opportunity_id == opportunity_id,
            OpportunityDeployment.status.in_(["deploying", "live", "down"])
        )
        .order_by(OpportunityDeployment.deployed_at.desc())
        .first()
    )
    
    if not deployment:
        raise HTTPException(
            status_code=404,
            detail=f"No active deployment found for opportunity {opportunity_id}"
        )
    
    # Undeploy
    logger.info(f"undeploying_mvp opportunity_id={opportunity_id} subdomain={deployment.subdomain}")
    
    deployer = DeployManager()
    project_slug = deployment.subdomain.split('.')[0]  # Extract slug from subdomain
    success = deployer.undeploy(project_slug)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to undeploy MVP for opportunity {opportunity_id}"
        )
    
    # Update status
    deployment.status = "removed"
    deployment.removed_at = datetime.utcnow()
    opportunity.deployed = False
    db.commit()
    
    logger.info(f"mvp_undeployed opportunity_id={opportunity_id}")
    
    return {
        "status": "success",
        "message": f"MVP undeployed successfully: {deployment.subdomain}",
        "data": deployment.to_dict(),
    }
