"""Typed schemas for deterministic copilot monitoring snapshots and findings."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.copilot import RecommendationStatus, RecommendedActionType

MonitoringDetectedIntent = Literal["monitoring_check"]
FindingType = Literal[
    "newly_eligible_recommendation",
    "holding_rule_violation",
    "holding_drawdown_breach",
    "watchlist_became_eligible",
    "best_eligible_asset_changed",
    "thesis_support_missing",
    "portfolio_concentration_warning",
    "missing_data",
]
FindingSeverity = Literal["info", "warning", "critical"]


class MonitoringAssetState(BaseModel):
    ticker: str
    rank: int
    recommendation_status: RecommendationStatus | None = None
    recommended_action_type: RecommendedActionType | None = None
    is_watchlist: bool = False
    is_holding: bool = False
    has_knowledge_support: bool = False
    drawdown_60d: float | None = None
    hard_conflicts: list[str] = Field(default_factory=list)
    concentration_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HoldingMonitoringState(BaseModel):
    ticker: str
    data_status: Literal["ok", "missing_data"] = "ok"
    recommendation_status: RecommendationStatus | None = None
    drawdown_60d: float | None = None
    drawdown_limit: float | None = None
    estimated_weight_pct: float | None = None
    concentration_limit_pct: float | None = None
    hard_conflicts: list[str] = Field(default_factory=list)
    concentration_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MonitoringSnapshotRecord(BaseModel):
    snapshot_id: str
    timestamp: str
    universe_tickers: list[str] = Field(default_factory=list)
    watchlist_tickers: list[str] = Field(default_factory=list)
    top_deterministic_result: str | None = None
    best_eligible_asset: str | None = None
    best_eligible_status: RecommendationStatus | None = None
    best_eligible_action: RecommendedActionType | None = None
    key_warnings: list[str] = Field(default_factory=list)
    monitored_assets: list[MonitoringAssetState] = Field(default_factory=list)
    holdings: list[HoldingMonitoringState] = Field(default_factory=list)


class MonitoringFinding(BaseModel):
    finding_id: str
    timestamp: str
    finding_type: FindingType
    severity: FindingSeverity
    entity: str | None = None
    headline: str
    summary: str
    why_it_matters: str
    suggested_next_action: str
    source_snapshot_ref: str


class SnapshotComparison(BaseModel):
    has_prior_snapshot: bool
    previous_best_eligible_asset: str | None = None
    current_best_eligible_asset: str | None = None
    best_eligible_asset_changed: bool = False
    previous_recommendation_status: RecommendationStatus | None = None
    current_recommendation_status: RecommendationStatus | None = None
    recommendation_status_changed: bool = False
    new_key_warnings: list[str] = Field(default_factory=list)
    cleared_key_warnings: list[str] = Field(default_factory=list)


class MonitoringRunRequest(BaseModel):
    instrument_tickers: list[str] | None = None
    top_n: int = Field(default=10, ge=1, le=50)
    save_snapshot: bool = True


class MonitoringRunResponse(BaseModel):
    summary: str
    current_snapshot: MonitoringSnapshotRecord
    comparison: SnapshotComparison
    findings: list[MonitoringFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FindingsListResponse(BaseModel):
    entries: list[MonitoringFinding]
    total: int
