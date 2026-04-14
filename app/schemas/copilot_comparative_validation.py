"""Typed schemas for deterministic local comparative validation over saved decisions."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ComparativeValidationDateRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None


class ComparativeCountItem(BaseModel):
    item: str
    count: int


class ComparisonGroup(BaseModel):
    comparison_key: str
    left_cohort: str
    right_cohort: str
    left_label: str
    right_label: str


class CohortSummary(BaseModel):
    cohort_key: str
    label: str
    total_decisions: int = 0
    later_recommendation_consistency_distribution: list[ComparativeCountItem] = Field(default_factory=list)
    current_relevance_status_distribution: list[ComparativeCountItem] = Field(default_factory=list)
    later_monitoring_signals_frequency: list[ComparativeCountItem] = Field(default_factory=list)
    watchlist_transition_status_distribution: list[ComparativeCountItem] = Field(default_factory=list)
    proportion_operationally_consistent: float | None = None
    proportion_still_actionable: float | None = None
    proportion_later_deteriorated: float | None = None
    proportion_still_best_eligible: float | None = None
    proportion_superseded_or_not_current: float | None = None
    proportion_later_receiving_negative_findings: float | None = None
    insufficient_data_markers: list[str] = Field(default_factory=list)


class RateComparisonSummary(BaseModel):
    comparison_key: str
    left_cohort: str
    right_cohort: str
    left_total: int
    right_total: int
    left_rate: float | None = None
    right_rate: float | None = None
    interpretation: str
    supported: bool = True
    notes: list[str] = Field(default_factory=list)


class LaterSignalComparisonSummary(BaseModel):
    comparison_key: str
    left_cohort: str
    right_cohort: str
    left_total: int
    right_total: int
    left_negative_findings_rate: float | None = None
    right_negative_findings_rate: float | None = None
    left_top_signals: list[ComparativeCountItem] = Field(default_factory=list)
    right_top_signals: list[ComparativeCountItem] = Field(default_factory=list)
    interpretation: str
    supported: bool = True
    notes: list[str] = Field(default_factory=list)


class ComparativeValidationRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    limit: int = Field(default=1000, ge=1, le=1000)


class ComparativeValidationResponse(BaseModel):
    generated_at: str
    date_range: ComparativeValidationDateRange
    comparison_groups: list[ComparisonGroup] = Field(default_factory=list)
    cohort_summaries: list[CohortSummary] = Field(default_factory=list)
    consistency_summary: list[RateComparisonSummary] = Field(default_factory=list)
    deterioration_summary: list[RateComparisonSummary] = Field(default_factory=list)
    later_signal_summary: list[LaterSignalComparisonSummary] = Field(default_factory=list)
    watchlist_transition_summary: list[RateComparisonSummary] = Field(default_factory=list)
    notable_patterns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)
