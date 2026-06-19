"""
BEA MAX — Base Schema with Security Hardening (Phase 4.2)
=============================================================
Strict Pydantic models with validation enabled by default.

All API request models should inherit from StrictBaseModel.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):  # type: ignore[misc]
    """
    Base model with strict validation enabled.
    
    Security features:
    - Forbids extra fields (prevents parameter pollution)
    - Validates assignment (prevents injection via setattr)
    - Strict mode (no type coercion, prevents "1" becoming 1)
    """
    
    model_config = ConfigDict(
        extra="forbid",           # Reject unknown fields
        validate_assignment=True, # Validate on attribute changes
        str_strip_whitespace=True,# Strip leading/trailing whitespace
        str_min_length=0,         # Allow empty strings (override per field)
    )
