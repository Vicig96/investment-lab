"""Typed schemas for deterministic local outcome attribution reviews."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OutcomeDateRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None


class ForwardSnapshotComparison(BaseModel):
    first_later_best_eligible_asset: str | None = None
    latest_best_eligible_asset: str | None = None
    first_later_best_eligible_status: str | None = None
    latest_best_eligible_status: str | None = None
    entity_matched_first_later_best: bool | None = None
    entity_matched_latest_best: bool | None = None


class DecisionOutcomeRecord(BaseModel):
    decision_id: str
    entity: str | None = None
    decision_timestamp: str
    days_elapsed: int
    action_taken: str | None = None
    was_reviewed: bool = False
    current_relevance_status: Literal[
        "no_entity_recorded",
        "no_later_monitoring_data",
        "still_best_eligible",
        "still_actionable_but_not_best",
        "superseded_or_not_current",
        "later_deteriorated",
    ]
    later_monitoring_signals: list[str] = Field(default_factory=list)
    later_recommendation_consistency: Literal["consistent", "changed", "mixed", "insufficient_data"]
    watchlist_transition_status: Literal[
        "not_watchlist_or_paper_only",
        "later_became_actionable",
        "no_later_actionable_transition_observed",
        "insufficient_data",
    ]
    forward_snapshot_comparison: ForwardSnapshotComparison | None = None
    warnings: list[str] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class OutcomeSummary(BaseModel):
    total_decisions_reviewed: int = 0
    reviewed_decisions: int = 0
    accepted_decisions: int = 0
    watchlist_or_paper_only_decisions: int = 0
    watchlist_or_paper_only_later_actionable: int = 0
    decisions_with_later_findings: int = 0
    consistent_recommendations: int = 0
    inconsistent_or_mixed_recommendations: int = 0


class OutcomeReviewRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    action_taken: str | None = None
    limit: int = Field(default=25, ge=1, le=1000)


class OutcomeReviewResponse(BaseModel):
    generated_at: str
    date_range: OutcomeDateRange
    summary: OutcomeSummary
    entries: list[DecisionOutcomeRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
