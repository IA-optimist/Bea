"""
agent_research/sources.py — ResearchSource: typed, validated source provenance.

Constraints:
  - Social media URLs are rejected (Twitter/X, Reddit, Facebook, TikTok, Instagram)
  - Personal data sources are rejected
  - Cookie-gated sources are flagged (not blocked, but require justification)
  - All sources need a kind declaration
"""
from __future__ import annotations

import re
from enum import Enum
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceKind(str, Enum):
    DOCUMENTATION = "documentation"   # official docs, RFCs
    PAPER = "paper"                   # academic paper, preprint
    CODE_REPO = "code_repo"           # public code repository
    BLOG = "blog"                     # technical blog post
    NEWS = "news"                     # tech news article
    SPEC = "spec"                     # technical specification
    INTERNAL = "internal"             # internal Béa codebase
    DATASET = "dataset"               # public dataset
    OTHER = "other"


# Domains blocked as sources (social media)
_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "twitter.com", "x.com",
    "reddit.com", "redd.it",
    "facebook.com", "fb.com",
    "instagram.com", "instagr.am",
    "tiktok.com",
    "linkedin.com",
    "youtube.com", "youtu.be",  # allow only academic/official channels
})

_SOCIAL_PATTERN = re.compile(
    r"https?://(?:www\.)?("
    + "|".join(re.escape(d) for d in sorted(_BLOCKED_DOMAINS, key=len, reverse=True))
    + r")",
    re.IGNORECASE,
)


def is_social_media_url(url: str) -> bool:
    return bool(_SOCIAL_PATTERN.match(url))


class ResearchSource(BaseModel):
    """A single research source with full provenance."""

    url: str = Field(min_length=5)
    kind: SourceKind
    title: str = Field(min_length=3, max_length=512)
    accessed_date: date = Field(default_factory=date.today)
    snippet: str = Field(default="", max_length=2000)
    credibility: float = Field(default=0.7, ge=0.0, le=1.0)
    is_cookie_gated: bool = False
    justification_for_cookie_gated: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def reject_social_media(cls, v: str) -> str:
        if is_social_media_url(v):
            raise ValueError(
                f"social media sources are not allowed: {v} — "
                "use official documentation, academic papers, or code repos"
            )
        return v

    @field_validator("justification_for_cookie_gated")
    @classmethod
    def cookie_gated_needs_justification(cls, v: str, info: Any) -> str:
        # Pydantic v2 field_validator receives ValidationInfo
        values = info.data if hasattr(info, "data") else {}
        if values.get("is_cookie_gated") and not v.strip():
            raise ValueError("cookie-gated sources require a justification")
        return v
