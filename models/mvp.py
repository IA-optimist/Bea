"""MVP (Minimum Viable Product) Model - Phase 7"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from models.base import Base


class MVP(Base):
    """Business MVP generated from opportunities."""
    
    __tablename__ = "mvps"
    
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, nullable=False, index=True)
    opportunity_id = Column(Integer, index=True)
    
    title = Column(String(512), nullable=False)
    description = Column(Text)
    
    status = Column(String(64), default="draft", index=True)
    # draft, generating, generated, deploying, deployed, failed
    
    tech_stack = Column(String(256))
    estimated_monthly_revenue = Column(Float, default=0.0)
    
    created_at = Column(DateTime, server_default=func.now())
    deployed_at = Column(DateTime, nullable=True)
