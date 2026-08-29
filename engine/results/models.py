"""Pydantic models for the single Frontend result document."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResultStatus = Literal[
    "OFFICIAL",
    "INCOMPLETE",
    "RANKING_OFFICIAL_PORTFOLIO_PENDING",
]


class RankingRecord(BaseModel):
    """A ranking row with the original Phase 3/5 metrics preserved."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)


class PortfolioRecord(BaseModel):
    """A selected or rotated Portfolio row."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)
    weight: float = Field(ge=0)
    theme: str | None = None
    base_rank: float | None = None
    tactical_rank: float | None = None
    status: str = Field(min_length=1)
    ytd: float | None = None
    mtd: float | None = None
    weekly: float | None = None


class ThemeReviewRecord(BaseModel):
    """A Tactical Top20 candidate that has no active Theme mapping."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)
    tactical_rank: float | None = None
    theme: str | None = None
    reason: str = Field(min_length=1)


class DataHealth(BaseModel):
    """Completeness metadata used to qualify the result status."""

    status: Literal["COMPLETE", "INCOMPLETE"]
    ranking_status: Literal["OFFICIAL", "INCOMPLETE"]
    portfolio_status: str = Field(min_length=1)
    universe_count: int = Field(ge=0)
    base_eligible_count: int = Field(ge=0)
    tactical_row_count: int = Field(ge=0)
    tactical_eligible_count: int = Field(ge=0)
    missing_tickers: list[str] = Field(default_factory=list)
    history_shortage_tickers: list[str] = Field(default_factory=list)
    download_failure_tickers: list[str] = Field(default_factory=list)
    benchmark_sources: dict[str, str] = Field(default_factory=dict)
    cache_data_status: str = Field(min_length=1)
    regime_data_status: str = Field(min_length=1)


class RankChange(BaseModel):
    """Weekly rank movement; positive change means rank improved."""

    model_config = ConfigDict(populate_by_name=True)

    ticker: str = Field(min_length=1)
    previous_rank: float | None = Field(default=None, alias="previousRank")
    current_rank: float | None = Field(default=None, alias="currentRank")
    rank_change: float | None = Field(default=None, alias="rankChange")


class PortfolioMovement(BaseModel):
    """One ticker in a weekly Portfolio transition."""

    model_config = ConfigDict(populate_by_name=True)

    ticker: str = Field(min_length=1)
    previous_rank: float | None = Field(default=None, alias="previousRank")
    current_rank: float | None = Field(default=None, alias="currentRank")


class Rotation(BaseModel):
    """Weekly ranking and Portfolio transitions."""

    model_config = ConfigDict(populate_by_name=True)

    rank_change: list[RankChange] = Field(default_factory=list, alias="rankChange")
    portfolio_in: list[PortfolioMovement] = Field(
        default_factory=list,
        alias="portfolioIn",
    )
    portfolio_out: list[PortfolioMovement] = Field(
        default_factory=list,
        alias="portfolioOut",
    )
    hold: list[PortfolioMovement] = Field(default_factory=list)


class ResultDocument(BaseModel):
    """Validated, self-contained document consumed by the Frontend."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    as_of: date = Field(alias="asOf")
    status: ResultStatus
    market_regime: dict[str, Any] = Field(alias="marketRegime")
    data_health: DataHealth = Field(alias="dataHealth")
    portfolio_status: str = Field(alias="portfolioStatus", min_length=1)
    theme_review: list[ThemeReviewRecord] = Field(
        default_factory=list,
        alias="themeReview",
    )
    portfolio: list[PortfolioRecord] = Field(default_factory=list)
    base_ranking: list[RankingRecord] = Field(alias="baseRanking")
    tactical_ranking: list[RankingRecord] = Field(alias="tacticalRanking")
    rotation: Rotation

    @model_validator(mode="after")
    def reject_duplicate_tickers(self) -> "ResultDocument":
        for field_name in ("base_ranking", "tactical_ranking", "portfolio"):
            rows = getattr(self, field_name)
            tickers = [row.ticker.strip().upper() for row in rows]
            if len(tickers) != len(set(tickers)):
                raise ValueError(f"duplicate ticker in {field_name}")
        return self
