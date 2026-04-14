"""Typed schemas for deterministic local forward-validation pilot reviews."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.copilot_shadow_portfolio import ShadowCohortKey


class ForwardPilotCountItem(BaseModel):
    item: str
    count: int


class ForwardPilotWindow(BaseModel):
    pilot_start: str | None = None
    pilot_end: str | None = None
    label: str | None = None


class ForwardPilotReviewProtocol(BaseModel):
    pilot_start: str | None = None
    pilot_end: str | None = None
    review_cadence: Literal["weekly"] = "weekly"
    total_decisions_in_period: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    watchlist_count: int = 0
    paper_only_count: int = 0
    eligible_count: int = 0
    blocked_count: int = 0
    findings_generated: int = 0
    findings_by_severity: list[ForwardPilotCountItem] = Field(default_factory=list)
    accepted_vs_paper_only_supported: bool = False
    hold_only_vs_exit_policy_supported: bool = False
    benchmark_comparison_supported: bool = False


class ForwardPilotOperationalSummary(BaseModel):
    total_decisions: int = 0
    reviewed_decisions: int = 0
    still_actionable_count: int = 0
    deteriorated_count: int = 0
    decisions_with_later_findings: int = 0
    snapshots_in_period: int = 0
    sample_size_note: str | None = None


class ForwardPilotDecisionSummary(BaseModel):
    decisions_by_action_taken: list[ForwardPilotCountItem] = Field(default_factory=list)
    decisions_by_recommendation_status: list[ForwardPilotCountItem] = Field(default_factory=list)
    top_blocked_reasons: list[ForwardPilotCountItem] = Field(default_factory=list)


class ForwardPilotMonitoringSummary(BaseModel):
    findings_generated: int = 0
    findings_by_severity: list[ForwardPilotCountItem] = Field(default_factory=list)
    findings_by_type: list[ForwardPilotCountItem] = Field(default_factory=list)
    snapshots_in_period: int = 0
    top_warning_patterns: list[ForwardPilotCountItem] = Field(default_factory=list)


class ForwardPilotPaperPortfolioSummary(BaseModel):
    cohort_definition: ShadowCohortKey = "accepted_plus_paper_only"
    supported_positions: int = 0
    unsupported_positions: int = 0
    hold_only_simple_return_pct: float | None = None
    exit_policy_simple_return_pct: float | None = None
    exit_policy_ending_value_difference: float | None = None
    active_positions_count: int = 0
    exited_positions_count: int = 0
    unsupported_exit_count: int = 0
    exit_reason_distribution: list[ForwardPilotCountItem] = Field(default_factory=list)


class ForwardPilotDirectionalComparison(BaseModel):
    supported: bool = False
    interpretation: str
    left_label: str
    right_label: str
    left_value: float | None = None
    right_value: float | None = None
    notes: list[str] = Field(default_factory=list)


class ForwardPilotCohortComparisonSummary(BaseModel):
    accepted_vs_paper_only: ForwardPilotDirectionalComparison
    hold_only_vs_exit_policy: ForwardPilotDirectionalComparison


class ForwardPilotBenchmarkSummary(BaseModel):
    supported: bool = False
    benchmark_ticker: str | None = None
    simple_return_pct: float | None = None
    interpretation: str
    notes: list[str] = Field(default_factory=list)


class ForwardValidationPilotRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    review_cadence: Literal["weekly"] = "weekly"
    paper_cohort_definition: ShadowCohortKey = "accepted_plus_paper_only"
    initial_capital: float = Field(default=10_000.0, gt=0)
    benchmark_ticker: str | None = "SPY"
    limit: int = Field(default=250, ge=1, le=1000)


class ForwardValidationPilotResponse(BaseModel):
    generated_at: str
    pilot_window: ForwardPilotWindow
    review_protocol: ForwardPilotReviewProtocol
    operational_summary: ForwardPilotOperationalSummary
    decision_summary: ForwardPilotDecisionSummary
    monitoring_summary: ForwardPilotMonitoringSummary
    paper_portfolio_summary: ForwardPilotPaperPortfolioSummary
    cohort_comparison_summary: ForwardPilotCohortComparisonSummary
    benchmark_summary: ForwardPilotBenchmarkSummary
    notable_patterns: list[str] = Field(default_factory=list)
    next_review_actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
