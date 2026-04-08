"""
OpportunityAnalysis SQLAlchemy model — P3.2 Feasibility Analysis
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from models.base import Base


class OpportunityAnalysis(Base):
    __tablename__ = "opportunity_analyses"
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    
    # Relationship (back-reference to Opportunity)
    # opportunity = relationship("Opportunity", back_populates="analyses")
    
    # Analysis metadata
    analyzed_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    analysis_duration_seconds = Column(Integer)
    
    # Cognition metadata
    mission_id = Column(String(50))
    confidence_score = Column(Float)
    cognition_reasoning = Column(Text)
    
    # Technical feasibility
    tech_stack = Column(JSONB)  # ["python", "fastapi", "react"]
    dependencies = Column(JSONB)  # ["stripe", "sendgrid"]
    complexity_score = Column(Integer)  # 1-10
    estimated_hours = Column(Integer)
    
    # MVP scope
    mvp_features = Column(JSONB)  # ["user_auth", "dashboard", "api"]
    nice_to_have_features = Column(JSONB)
    out_of_scope = Column(JSONB)
    
    # Risk assessment
    technical_risks = Column(JSONB)
    mitigation_strategies = Column(JSONB)
    
    # Recommendations
    recommendation = Column(Text)  # BUILD, SKIP, NEEDS_MORE_RESEARCH
    reasoning = Column(Text)
    market_fit_score = Column(Float)  # 0-100
    
    # Full analysis
    full_analysis = Column(Text)
    raw_output = Column(JSONB)
    
    # Status
    approved = Column(Boolean, default=False)
    approved_by = Column(String(100))
    approved_at = Column(TIMESTAMP)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict"""
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "cognition": {
                "mission_id": self.mission_id,
                "confidence_score": round(self.confidence_score, 3) if self.confidence_score else None,
                "reasoning": self.cognition_reasoning,
            },
            "technical": {
                "tech_stack": self.tech_stack or [],
                "dependencies": self.dependencies or [],
                "complexity_score": self.complexity_score,
                "estimated_hours": self.estimated_hours,
            },
            "mvp_scope": {
                "features": self.mvp_features or [],
                "nice_to_have": self.nice_to_have_features or [],
                "out_of_scope": self.out_of_scope or [],
            },
            "risks": {
                "technical_risks": self.technical_risks or [],
                "mitigation": self.mitigation_strategies or [],
            },
            "recommendation": {
                "decision": self.recommendation,
                "reasoning": self.reasoning,
                "market_fit_score": round(self.market_fit_score, 2) if self.market_fit_score else None,
            },
            "full_analysis": self.full_analysis,
            "status": {
                "approved": self.approved,
                "approved_by": self.approved_by,
                "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
