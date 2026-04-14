"""Typed schemas for deterministic local shadow portfolio reviews."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ShadowCohortKey = Literal[
    "accepted",
    "paper_only",
    "accepted_plus_paper_only",
    "watchlist_later_actionable",
]


class ShadowDateRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None


class ShadowCohortDefinition(BaseModel):
    cohort_key: ShadowCohortKey
    label: str
    weighting: Literal["equal_weight"] = "equal_weight"
    benchmark_ticker: str | None = "SPY"


class ShadowPaperPosition(BaseModel):
    decision_id: str
    entity: str | None = None
    decision_timestamp: str
    assumed_entry_timestamp: str | None = None
    assumed_entry_price: float | None = None
    latest_mark_timestamp: str | None = None
    latest_mark_price: float | None = None
    supported: bool
    support_notes: list[str] = Field(default_factory=list)
    simple_return_pct: float | None = None


class ShadowPaperSummary(BaseModel):
    total_positions: int = 0
    supported_positions: int = 0
    unsupported_positions: int = 0
    average_simple_return_pct: float | None = None
    median_simple_return_pct: float | None = None
    equal_weight_simple_return_pct: float | None = None
    positive_count: int = 0
    negative_count: int = 0


class ShadowBenchmarkSummary(BaseModel):
    benchmark_ticker: str | None = None
    supported: bool = False
    assumed_entry_timestamp: str | None = None
    assumed_entry_price: float | None = None
    latest_mark_timestamp: str | None = None
    latest_mark_price: float | None = None
    simple_return_pct: float | None = None
    support_notes: list[str] = Field(default_factory=list)


class ShadowComparisonSummary(BaseModel):
    benchmark_comparison_supported: bool = False
    benchmark_ticker: str | None = None
    cohort_equal_weight_simple_return_pct: float | None = None
    benchmark_simple_return_pct: float | None = None
    interpretation: str
    notes: list[str] = Field(default_factory=list)


class ShadowPortfolioRequest(BaseModel):
    cohort_definition: ShadowCohortKey = "accepted_plus_paper_only"
    date_from: str | None = None
    date_to: str | None = None
    benchmark_ticker: str | None = "SPY"
    limit: int = Field(default=250, ge=1, le=1000)


class ShadowPortfolioResponse(BaseModel):
    generated_at: str
    date_range: ShadowDateRange
    cohort_definition: ShadowCohortDefinition
    paper_positions: list[ShadowPaperPosition] = Field(default_factory=list)
    supported_positions: int = 0
    unsupported_positions: int = 0
    paper_summary: ShadowPaperSummary
    benchmark_summary: ShadowBenchmarkSummary
    comparison_summary: ShadowComparisonSummary
    warnings: list[str] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
