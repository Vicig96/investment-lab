"""Typed schemas for deterministic local paper portfolio NAV reviews."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.copilot_shadow_portfolio import ShadowCohortKey


class PaperPortfolioDateRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None


class PaperPortfolioCohortDefinition(BaseModel):
    cohort_key: ShadowCohortKey
    label: str


class PaperPortfolioAssumptions(BaseModel):
    entry_rule: str
    allocation_rule: str
    cash_ledger_rule: str
    mark_to_market_rule: str
    duplicate_entry_rule: str
    lifecycle_rule: str
    exit_policy_rule: str
    benchmark_rule: str


class PaperPortfolioCountItem(BaseModel):
    item: str
    count: int


class PaperPortfolioNavPoint(BaseModel):
    date: str
    portfolio_value: float
    cash: float
    invested_value: float
    active_position_count: int


class PaperPortfolioPositionSummary(BaseModel):
    decision_id: str
    entity: str | None = None
    assumed_entry_timestamp: str | None = None
    assumed_entry_price: float | None = None
    exit_policy_status: Literal[
        "hold_to_window_end",
        "exited_on_replacement",
        "exited_on_deterioration",
        "exited_on_hard_conflict",
        "exited_on_negative_signal",
        "unsupported_exit_decision",
    ] = "hold_to_window_end"
    exit_trigger_type: Literal["replacement", "deterioration", "hard_conflict", "negative_signal"] | None = None
    exit_trigger_timestamp: str | None = None
    assumed_exit_timestamp: str | None = None
    assumed_exit_price: float | None = None
    realized_or_closed_simple_return_pct: float | None = None
    current_mark_timestamp: str | None = None
    current_mark_price: float | None = None
    allocated_capital: float = 0.0
    current_value: float | None = None
    simple_return_pct: float | None = None
    supported: bool
    supported_exit: bool | None = None
    support_notes: list[str] = Field(default_factory=list)
    lifecycle_notes: list[str] = Field(default_factory=list)
    lifecycle_status: Literal["active", "exited", "inactive_duplicate", "unsupported_missing_data"] = "active"


class PaperPortfolioNavSummary(BaseModel):
    total_positions_entered: int = 0
    supported_positions: int = 0
    unsupported_positions: int = 0
    total_portfolio_simple_return_pct: float | None = None
    max_paper_drawdown_pct: float | None = None
    average_position_simple_return_pct: float | None = None
    median_position_simple_return_pct: float | None = None
    positive_positions_count: int = 0
    negative_positions_count: int = 0


class PaperPortfolioBenchmarkSummary(BaseModel):
    benchmark_ticker: str | None = None
    supported: bool = False
    assumed_entry_timestamp: str | None = None
    assumed_entry_price: float | None = None
    latest_mark_timestamp: str | None = None
    latest_mark_price: float | None = None
    simple_return_pct: float | None = None
    ending_value: float | None = None
    support_notes: list[str] = Field(default_factory=list)


class PaperPortfolioComparisonSummary(BaseModel):
    benchmark_comparison_supported: bool = False
    benchmark_ticker: str | None = None
    portfolio_simple_return_pct: float | None = None
    benchmark_simple_return_pct: float | None = None
    hold_to_window_end_ending_value: float | None = None
    exit_policy_ending_value_difference: float | None = None
    interpretation: str
    notes: list[str] = Field(default_factory=list)


class PaperPortfolioHoldExitPolicySummary(BaseModel):
    applied: bool = False
    policy_version: str = "hold_only_v0"
    active_positions_count: int = 0
    exited_positions_count: int = 0
    unsupported_exit_count: int = 0
    exit_reason_distribution: list[PaperPortfolioCountItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PaperPortfolioNavRequest(BaseModel):
    cohort_definition: ShadowCohortKey = "accepted"
    date_from: str | None = None
    date_to: str | None = None
    initial_capital: float = Field(default=10_000.0, gt=0)
    benchmark_ticker: str | None = "SPY"
    apply_exit_policy: bool = False
    limit: int = Field(default=250, ge=1, le=1000)


class PaperPortfolioNavResponse(BaseModel):
    generated_at: str
    date_range: PaperPortfolioDateRange
    cohort_definition: PaperPortfolioCohortDefinition
    assumptions: PaperPortfolioAssumptions
    initial_capital: float
    ending_value: float
    cash_remaining: float
    active_positions_count: int = 0
    exited_positions_count: int = 0
    unsupported_exit_count: int = 0
    exit_reason_distribution: list[PaperPortfolioCountItem] = Field(default_factory=list)
    active_positions: list[str] = Field(default_factory=list)
    closed_or_inactive_positions: list[str] = Field(default_factory=list)
    hold_exit_policy_summary: PaperPortfolioHoldExitPolicySummary
    nav_summary: PaperPortfolioNavSummary
    nav_points: list[PaperPortfolioNavPoint] = Field(default_factory=list)
    position_summaries: list[PaperPortfolioPositionSummary] = Field(default_factory=list)
    benchmark_summary: PaperPortfolioBenchmarkSummary
    comparison_summary: PaperPortfolioComparisonSummary
    warnings: list[str] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
