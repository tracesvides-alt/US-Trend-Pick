"""Typed models for automatic Theme classification and history."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ThemeConfidence = Literal["HIGH", "MEDIUM", "LOW"]


class ThemeDefinition(BaseModel):
    """One canonical Primary Theme from the fixed master catalog."""

    name: str = Field(min_length=1)
    description: str | None = None


class CompanyProfile(BaseModel):
    """Free company metadata used as Theme classifier input."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    business_summary: str | None = None


class ThemeClassification(BaseModel):
    """Point-in-time Theme result for one ticker."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)
    primary_theme: str = Field(min_length=1)
    theme_score: float = Field(ge=0, le=100)
    second_theme: str = Field(min_length=1)
    second_theme_score: float = Field(ge=0, le=100)
    confidence: ThemeConfidence
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    as_of: date
    proposed_theme: str | None = None
    proposed_theme_score: float | None = Field(default=None, ge=0, le=100)
    previous_theme: str | None = None
    theme_changed: bool = False
    change_reason: str | None = None
    keyword_hits: dict[str, list[str]] = Field(default_factory=dict)
    theme_scores: dict[str, float] = Field(default_factory=dict)


class ThemeHistoryRecord(BaseModel):
    """One automatically maintained inclusive Theme validity interval."""

    ticker: str = Field(min_length=1)
    primary_theme: str = Field(min_length=1)
    effective_from: date
    effective_to: date | None = None


class ThemeChangeRecord(BaseModel):
    """A Primary Theme change, separate from weekly rank rotation."""

    ticker: str = Field(min_length=1)
    previous_theme: str = Field(min_length=1)
    new_theme: str = Field(min_length=1)
    as_of: date
    reason: str = Field(min_length=1)


class ThemeRunResult(BaseModel):
    """Artifacts produced by one automatic Theme classification run."""

    as_of: date
    classifications: list[ThemeClassification] = Field(default_factory=list)
    history: list[ThemeHistoryRecord] = Field(default_factory=list)
    changes: list[ThemeChangeRecord] = Field(default_factory=list)
    profile_failures: dict[str, str] = Field(default_factory=dict)
