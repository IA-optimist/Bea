"""
BeaMax — Products API
REST endpoints for product catalogue management
"""
from __future__ import annotations

import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api._deps import require_auth, get_db
from models.product import Product

router = APIRouter(
    prefix="/api/v3/business/products",
    tags=["products"],
    dependencies=[Depends(require_auth)],
)


def _response(data=None, message: str = "ok", status: str = "success") -> dict:
    return {"status": status, "message": message, "data": data, "timestamp": time.time()}


# ── Request models ──────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="")
    category: str = Field(default="saas")
    status: str = Field(default="active")
    version: str = Field(default="1.0.0")
    price: float = Field(default=0.0, ge=0.0)
    deployment_url: Optional[str] = None
    source_opportunity_id: Optional[int] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    version: Optional[str] = None
    price: Optional[float] = Field(None, ge=0.0)
    deployment_url: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_products(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    query = db.query(Product)
    if category:
        query = query.filter(Product.category == category)
    if status:
        query = query.filter(Product.status == status)
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    total = query.count()
    items = query.order_by(desc(Product.created_at)).offset((page - 1) * page_size).limit(page_size).all()
    return _response(data={
        "items": [p.to_dict() for p in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    })


@router.get("/{product_id}", response_model=dict)
async def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _response(data=product.to_dict())


@router.post("", response_model=dict, status_code=201)
async def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**body.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return _response(data=product.to_dict(), message="Product created")


@router.patch("/{product_id}", response_model=dict)
async def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _response(data=product.to_dict(), message="Product updated")


@router.delete("/{product_id}", response_model=dict)
async def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return _response(message="Product deleted")


@router.post("/{product_id}/deploy", response_model=dict)
async def deploy_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = "deploying"
    db.commit()

    def _run_deploy():
        try:
            db.refresh(product)
            product.status = "deployed"
            db.commit()
        except Exception:
            pass

    background_tasks.add_task(_run_deploy)
    return _response(
        data={"job_id": f"deploy-{product_id}-{int(time.time())}", "product_id": product_id},
        message="Deployment started",
    )
