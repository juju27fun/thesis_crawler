from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

AiCategory = Literal[
    "ml_deep_learning",
    "generative_ai",
    "general_ai",
    "data_science_adjacent",
    "not_relevant",
]


class ListPageStats(BaseModel):
    total_offers: int | None = None
    total_pages: int | None = None


class JobOffer(BaseModel):
    source: Literal["cnrs"] = "cnrs"
    url: HttpUrl
    reference: str | None = None
    title: str
    contract_type: str | None = None
    duration: str | None = None
    education_level: str | None = None
    experience_level: str | None = None
    location: str | None = None
    lab: str | None = None
    published_at_text: str | None = None
    description: str | None = None
    skills: str | None = None
    raw_text: str = ""
    unavailable: bool = False
    hard_filter_passed: bool = False
    ai_relevance_score: float | None = Field(default=None, ge=0, le=1)
    ai_category: AiCategory | None = None
    ai_reason: str | None = None
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Classification(BaseModel):
    is_target: bool
    target_type: Literal["thesis_or_bac5_cdd", "bac5_cdd", "not_target"]
    ai_domain: AiCategory
    relevance_score: float = Field(ge=0, le=1)
    accessibility: Literal["bac5_accessible", "doctorate_required", "unclear", "not_accessible"]
    reason: str

