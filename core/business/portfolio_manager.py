"""
Phase 7.2: Multi-Project Business Portfolio Manager

Tracks business opportunities, MVPs, and revenue streams per project.
Enables cross-project skill transfer and portfolio-wide analytics.
"""
from __future__ import annotations
import structlog
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from models.opportunity import Opportunity
from models.mvp import MVP

log = structlog.get_logger(__name__)


class PortfolioManager:
    """Manage business portfolio across multiple JarvisMax projects."""
    
    def __init__(self, db_session: Session):
        self.db = db_session
    
    def get_project_opportunities(
        self,
        project_id: int,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Opportunity]:
        """Get opportunities for a specific project."""
        query = select(Opportunity).where(
            Opportunity.project_id == project_id
        )
        
        if status:
            query = query.where(Opportunity.status == status)
        
        query = query.order_by(Opportunity.total_score.desc()).limit(limit)
        
        return list(self.db.execute(query).scalars())
    
    def get_project_mvps(
        self,
        project_id: int,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[MVP]:
        """Get MVPs for a specific project."""
        query = select(MVP).where(MVP.project_id == project_id)
        
        if status:
            query = query.where(MVP.status == status)
        
        query = query.order_by(MVP.created_at.desc()).limit(limit)
        
        return list(self.db.execute(query).scalars())
    
    def get_project_metrics(self, project_id: int) -> Dict[str, Any]:
        """Get business metrics for a specific project."""
        
        # Count opportunities by status
        opp_counts = self.db.execute(
            select(
                Opportunity.status,
                func.count(Opportunity.id)
            ).where(
                Opportunity.project_id == project_id
            ).group_by(Opportunity.status)
        ).all()
        
        # Count MVPs by status
        mvp_counts = self.db.execute(
            select(
                MVP.status,
                func.count(MVP.id)
            ).where(
                MVP.project_id == project_id
            ).group_by(MVP.status)
        ).all()
        
        # Sum estimated revenue
        revenue_result = self.db.execute(
            select(func.sum(MVP.estimated_monthly_revenue)).where(
                MVP.project_id == project_id,
                MVP.status == 'deployed'
            )
        ).scalar()
        
        estimated_revenue = float(revenue_result or 0)
        
        return {
            "project_id": project_id,
            "opportunities": {
                status: count for status, count in opp_counts
            },
            "mvps": {
                status: count for status, count in mvp_counts
            },
            "estimated_monthly_revenue": estimated_revenue,
            "currency": "EUR",
        }
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio-wide metrics across all projects."""
        
        # Total opportunities
        total_opps = self.db.execute(
            select(func.count(Opportunity.id))
        ).scalar() or 0
        
        # Total MVPs
        total_mvps = self.db.execute(
            select(func.count(MVP.id))
        ).scalar() or 0
        
        # Deployed MVPs
        deployed_mvps = self.db.execute(
            select(func.count(MVP.id)).where(MVP.status == 'deployed')
        ).scalar() or 0
        
        # Total estimated revenue
        total_revenue = self.db.execute(
            select(func.sum(MVP.estimated_monthly_revenue)).where(
                MVP.status == 'deployed'
            )
        ).scalar() or 0
        
        # Active projects (projects with opportunities or MVPs)
        active_projects = self.db.execute(
            select(func.count(func.distinct(Opportunity.project_id)))
        ).scalar() or 0
        
        # Top opportunities
        top_opps = self.db.execute(
            select(Opportunity).order_by(
                Opportunity.total_score.desc()
            ).limit(5)
        ).scalars().all()
        
        return {
            "total_opportunities": total_opps,
            "total_mvps": total_mvps,
            "deployed_mvps": deployed_mvps,
            "active_projects": active_projects,
            "estimated_monthly_revenue": float(total_revenue),
            "currency": "EUR",
            "top_opportunities": [
                {
                    "id": opp.id,
                    "title": opp.title,
                    "score": opp.total_score,
                    "project_id": opp.project_id,
                }
                for opp in top_opps
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def transfer_skills(
        self,
        from_project_id: int,
        to_project_id: int,
        skill_names: List[str]
    ) -> Dict[str, Any]:
        """
        Transfer learned skills from one project to another.
        
        Used when a project discovers valuable patterns/skills
        that should be available to other projects.
        """
        from core.cognition.project_context import ProjectContextManager
        
        # Initialize project manager
        pm = ProjectContextManager()
        
        # Get source project skills
        source_skills = pm.get_all_skills(include_global=False)
        
        # Filter requested skills
        skills_to_transfer = [
            s for s in skill_names if s in source_skills
        ]
        
        # Add to target project
        for skill in skills_to_transfer:
            pm.add_learned_skill(to_project_id, skill)
        
        log.info(
            "skills_transferred",
            from_project=from_project_id,
            to_project=to_project_id,
            skills=skills_to_transfer,
            count=len(skills_to_transfer)
        )
        
        return {
            "transferred": skills_to_transfer,
            "count": len(skills_to_transfer),
            "from_project": from_project_id,
            "to_project": to_project_id,
        }
    
    def get_cross_project_patterns(self) -> Dict[str, Any]:
        """
        Analyze patterns across all projects to identify
        successful strategies, common tech stacks, etc.
        """
        
        # Get all successful MVPs (deployed + revenue > 0)
        successful_mvps = self.db.execute(
            select(MVP).where(
                MVP.status == 'deployed',
                MVP.estimated_monthly_revenue > 0
            )
        ).scalars().all()
        
        # Extract patterns
        tech_stacks = {}
        categories = {}
        avg_revenue_by_category = {}
        
        for mvp in successful_mvps:
            # Count tech stack usage
            stack = mvp.tech_stack or "unknown"
            tech_stacks[stack] = tech_stacks.get(stack, 0) + 1
            
            # Count categories
            category = getattr(mvp, 'category', 'general')
            categories[category] = categories.get(category, 0) + 1
            
            # Track revenue by category
            if category not in avg_revenue_by_category:
                avg_revenue_by_category[category] = []
            avg_revenue_by_category[category].append(
                mvp.estimated_monthly_revenue or 0
            )
        
        # Calculate averages
        avg_revenue = {
            cat: sum(revs) / len(revs) if revs else 0
            for cat, revs in avg_revenue_by_category.items()
        }
        
        return {
            "successful_mvps_count": len(successful_mvps),
            "popular_tech_stacks": dict(
                sorted(tech_stacks.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "popular_categories": dict(
                sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "avg_revenue_by_category": avg_revenue,
            "total_portfolio_revenue": sum(
                mvp.estimated_monthly_revenue or 0
                for mvp in successful_mvps
            ),
        }
