"""
JarvisMax P3.4 — Opportunity Deployment Model
Tracks deployed MVPs on VPS.
"""

from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, Boolean, DECIMAL
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

from models.base import Base


class OpportunityDeployment(Base):
    __tablename__ = "opportunity_deployments"
    
    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # GitHub
    repo_name = Column(String(255), nullable=False)
    repo_url = Column(Text, nullable=False)
    clone_url = Column(Text)
    html_url = Column(Text)
    
    # Deployment
    deployed_at = Column(TIMESTAMP, default=_utc_now)
    deploy_path = Column(Text, nullable=False)
    subdomain = Column(String(255), nullable=False, unique=True, index=True)
    url = Column(Text, nullable=False)
    
    # Status
    status = Column(String(50), default="deploying", index=True)  # deploying, live, down, removed
    last_health_check = Column(TIMESTAMP)
    uptime_percent = Column(DECIMAL(5, 2), default=100.0)
    
    # Metadata
    deploy_duration_seconds = Column(Integer)
    docker_image_tag = Column(String(100))
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=_utc_now)
    updated_at = Column(TIMESTAMP, default=_utc_now, onupdate=_utc_now)
    removed_at = Column(TIMESTAMP)
    
    def to_dict(self):
        """Convert to dict for API responses"""
        return {
            "id": self.id,
            "opportunity_id": self.opportunity_id,
            "github": {
                "repo_name": self.repo_name,
                "repo_url": self.repo_url,
                "clone_url": self.clone_url,
                "html_url": self.html_url,
            },
            "deployment": {
                "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
                "deploy_path": self.deploy_path,
                "subdomain": self.subdomain,
                "url": self.url,
                "deploy_duration_seconds": self.deploy_duration_seconds,
                "docker_image_tag": self.docker_image_tag,
            },
            "status": {
                "status": self.status,
                "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
                "uptime_percent": float(self.uptime_percent) if self.uptime_percent else 100.0,
            },
            "timestamps": {
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "removed_at": self.removed_at.isoformat() if self.removed_at else None,
            },
        }
