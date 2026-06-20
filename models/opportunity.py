"""
Opportunity Model — SaaS business opportunities discovered by scanner
"""
from __future__ import annotations

from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from models.base import Base


class Opportunity(Base):
    """A business opportunity discovered by the opportunity scanner"""
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)

    # Core fields
    title = Column(String(500), nullable=False, index=True)
    description = Column(Text, nullable=False)
    source = Column(String(50), nullable=False, index=True)  # product_hunt, reddit, hackernews, indie_hackers
    url = Column(String(1000), nullable=False)
    discovered_at = Column(DateTime, nullable=False, default=_utc_now, index=True)

    # Metrics
    upvotes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    mentions = Column(Integer, default=1)

    # Scores (0-100)
    demand_score = Column(Float, default=0.0, index=True)
    competition_score = Column(Float, default=0.0)
    feasibility_score = Column(Float, default=0.0)
    monetization_score = Column(Float, default=0.0, index=True)
    total_score = Column(Float, default=0.0, index=True)

    # Tags & analysis
    tags = Column(JSONB, default=list)  # ["saas", "b2b", "automation"]
    pain_points = Column(JSONB, default=list)  # Extracted pain points

    # Processing status
    analyzed = Column(Boolean, default=False, index=True)  # Feasibility analysis done?
    mvp_generated = Column(Boolean, default=False)
    deployed = Column(Boolean, default=False)

    # Metadata
    raw_data = Column(JSONB, nullable=True)  # Full scraped data
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)

    def __repr__(self):
        return f"<Opportunity(id={self.id}, title='{self.title[:50]}...', total_score={self.total_score})>"

    def to_dict(self) -> dict:
        """Serialize to dict"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "url": self.url,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "metrics": {
                "upvotes": self.upvotes,
                "comments": self.comments,
                "mentions": self.mentions,
            },
            "scores": {
                "demand": round(self.demand_score, 2),
                "competition": round(self.competition_score, 2),
                "feasibility": round(self.feasibility_score, 2),
                "monetization": round(self.monetization_score, 2),
                "total": round(self.total_score, 2),
            },
            "tags": self.tags or [],
            "pain_points": self.pain_points or [],
            "status": {
                "analyzed": self.analyzed,
                "mvp_generated": self.mvp_generated,
                "deployed": self.deployed,
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
