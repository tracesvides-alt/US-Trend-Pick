"""Typed models shared by universe acquisition and snapshot generation."""

from datetime import date

from pydantic import BaseModel, Field


class Holding(BaseModel):
    """One constituent parsed from a published holdings or index response."""

    ticker: str
    company_name: str


class SourceResult(BaseModel):
    """Result of trying the configured sources for one target universe."""

    name: str
    holdings: list[Holding] = Field(default_factory=list)
    selected_source: str | None = None
    as_of: date | None = None
    errors: list[str] = Field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """Whether a sufficiently complete source was selected."""
        return self.selected_source is not None and bool(self.holdings)


class UniverseMember(BaseModel):
    """A normalized, deduplicated member of the integrated universe."""

    ticker: str
    company_name: str
    source_spy: bool = False
    source_qqq: bool = False
    source_qqqj: bool = False
    as_of: date


class UniverseBuildReport(BaseModel):
    """Counts and source diagnostics emitted by a completed build."""

    spy: SourceResult
    qqq: SourceResult
    qqqj: SourceResult
    members: list[UniverseMember] = Field(default_factory=list)
    duplicate_removed: int = 0
    snapshot_path: str | None = None

