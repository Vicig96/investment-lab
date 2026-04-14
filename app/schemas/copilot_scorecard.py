"""Typed schemas for deterministic local copilot scorecards."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScorecardDateRange(BaseModel):
    start: str | None = None
    end: str | None = None
    label: str | None = None


class CountItem(BaseModel):
    item: str
    count: int


class JournalScorecardSummary(BaseModel):
    total_journal_decisions: int = 0
    top_deterministic_results: list[CountItem] = Field(default_factory=list)
    top_final_recommendations: list[CountItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class RecommendationScorecardSummary(BaseModel):
    decisions_by_recommendation_status: list[CountItem] = Field(default_factory=list)
    eligible_ideas_acted_on: int = 0
    missing_data_notes: list[str] = Field(default_factory=list)


class ActionScorecardSummary(BaseModel):
    decisions_by_action_taken: list[CountItem] = Field(default_factory=list)
    decisions_by_recommended_action_type: list[CountItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class ConstraintScorecardSummary(BaseModel):
    top_blocked_or_rejected_reasons: list[CountItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class FindingsScorecardSummary(BaseModel):
    total_findings: int = 0
    findings_by_finding_type: list[CountItem] = Field(default_factory=list)
    findings_by_severity: list[CountItem] = Field(default_factory=list)
    most_frequent_entities: list[CountItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class MonitoringScorecardSummary(BaseModel):
    snapshots_in_range: int = 0
    best_eligible_asset_changes: int = 0
    watchlist_or_paper_only_later_actionable_count: int | None = None
    top_key_warning_patterns: list[CountItem] = Field(default_factory=list)
    missing_data_notes: list[str] = Field(default_factory=list)


class ScorecardRequest(BaseModel):
    date_from: str | None = None
    date_to: str | None = None


class ScorecardResponse(BaseModel):
    generated_at: str
    date_range: ScorecardDateRange
    journal_summary: JournalScorecardSummary
    recommendation_summary: RecommendationScorecardSummary
    action_summary: ActionScorecardSummary
    constraint_summary: ConstraintScorecardSummary
    findings_summary: FindingsScorecardSummary
    monitoring_summary: MonitoringScorecardSummary
    notable_patterns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
