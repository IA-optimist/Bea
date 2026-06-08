"""
Product Model — products built/deployed by Béa
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from models.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=False, default="")
    category = Column(String(100), nullable=False, default="saas", index=True)
    status = Column(String(50), nullable=False, default="active", index=True)
    version = Column(String(50), nullable=False, default="1.0.0")
    price = Column(Float, nullable=False, default=0.0)
    deployment_url = Column(String(1000), nullable=True)
    source_opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "status": self.status,
            "version": self.version,
            "price": self.price,
            "deployment_url": self.deployment_url,
            "source_opportunity_id": self.source_opportunity_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
