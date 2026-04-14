"""Structured schemas for the Investment Copilot tool layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.backtest import BacktestMetrics

RecommendationStatus = Literal[
    "eligible",
    "eligible_with_cautions",
    "rejected_by_profile",
    "unsupported_by_knowledge",
    "eligible_new_position",
    "eligible_add_to_existing",
    "eligible_but_overconcentrated",
    "rejected_by_portfolio_constraints",
    "not_actionable_without_cash",
    "redundant_exposure",
]

RecommendedActionType = Literal[
    "open_new_position",
    "add_to_existing_position",
    "avoid",
    "no_action",
    "review_only",
]


class CopilotToolSpec(BaseModel):
    name: str
    description: str
    route: str
    method: Literal["GET", "POST"] = "POST"


class CopilotToolsResponse(BaseModel):
    tools: list[CopilotToolSpec]


class MarketSnapshotRequest(BaseModel):
    instrument_tickers: list[str]
    date_from: date | None = None
    date_to: date | None = None


class DataCoverage(BaseModel):
    start_date: str | None
    end_date: str | None
    history_bars: int
    latest_date: str | None


class TrendMetrics(BaseModel):
    dist_sma_50: float | None
    dist_sma_200: float | None
    trend_score: float | None


class RecentReturns(BaseModel):
    ret_20d: float | None
    ret_60d: float | None
    ret_120d: float | None


class AssetMarketSnapshot(BaseModel):
    ticker: str
    latest_price: float | None
    latest_date: str | None
    recent_returns: RecentReturns
    volatility_20d: float | None
    drawdown_60d: float | None
    trend: TrendMetrics
    data_quality: str
    history_coverage: DataCoverage
    warnings: list[str]


class MarketSnapshotResponse(BaseModel):
    tool_name: Literal["get_market_snapshot"] = "get_market_snapshot"
    snapshot_date: str | None
    requested_tickers: list[str]
    assets: list[AssetMarketSnapshot]
    warnings: list[str]


class RankAssetsRequest(BaseModel):
    instrument_tickers: list[str]
    top_n: int = Field(default=5, ge=1, le=50)
    date_from: date | None = None
    date_to: date | None = None


class ScoreBreakdown(BaseModel):
    ret_60d_contribution: float
    ret_20d_contribution: float
    ret_120d_contribution: float
    trend_contribution: float
    low_volatility_contribution: float
    low_drawdown_contribution: float
    total_score: float


class RankedAssetCopilot(BaseModel):
    ticker: str
    score: float
    label: str
    suggested_weight: float | None
    history_bars: int
    data_quality: str
    insufficient_history_reason: str | None
    recent_returns: RecentReturns
    volatility_20d: float | None
    drawdown_60d: float | None
    trend: TrendMetrics
    score_breakdown: ScoreBreakdown
    warnings: list[str]


class RankAssetsResponse(BaseModel):
    tool_name: Literal["rank_assets"] = "rank_assets"
    snapshot_date: str
    universe_size: int
    top_n: int
    ranked_assets: list[RankedAssetCopilot]
    warnings: list[str]


class StrategyEvaluationRequest(BaseModel):
    run_mode: Literal["single", "compare_variants", "parameter_sweep", "cross_preset", "walk_forward"]
    instrument_tickers: list[str]
    date_from: date | None = None
    date_to: date | None = None
    top_n: int = Field(default=3, ge=1, le=20)
    top_n_values: list[int] = Field(default_factory=lambda: [1, 2, 3])
    initial_capital: float = Field(default=10_000.0, gt=0)
    commission_bps: float = Field(default=10.0, ge=0)
    rebalance_frequency: Literal["monthly"] = "monthly"
    warmup_bars: int = Field(default=252, ge=0, le=1000)
    defensive_mode: Literal["cash", "defensive_asset"] = "cash"
    defensive_tickers: list[str] = Field(default_factory=lambda: ["TLT", "GLD"])
    wf_data_start: date | None = None
    wf_data_end: date | None = None
    wf_train_years: int = Field(default=2, ge=1, le=10)
    wf_test_years: int = Field(default=1, ge=1, le=10)
    wf_step_years: int = Field(default=1, ge=1, le=10)


class BenchmarkSummary(BaseModel):
    ticker: str = "SPY"
    metrics: BacktestMetrics


class StrategyConfigSummary(BaseModel):
    config_key: str
    top_n: int | None
    defensive_mode: str | None
    metrics: BacktestMetrics | None
    benchmark_metrics: BacktestMetrics | None = None
    status: Literal["ok", "error"] = "ok"
    error: str | None = None


class CrossPresetRankingRow(BaseModel):
    config_key: str
    bull_run_avg_rank: float | None
    rate_hike_bear_avg_rank: float | None
    mixed_volatile_avg_rank: float | None
    full_cycle_avg_rank: float | None
    average_rank: float | None
    rank_std_dev: float | None
    times_ranked_1: int
    times_ranked_top_2: int
    robustness_score: float | None
    avg_cagr: float | None
    avg_abs_drawdown: float | None


class CrossPresetSummary(BaseModel):
    overall_winner: str | None
    most_robust_config: str | None
    best_bull_market_config: str | None
    best_bear_market_config: str | None
    best_return_config: str | None
    best_drawdown_control_config: str | None
    recommended_default_config: str | None
    ranking_rows: list[CrossPresetRankingRow]


class WalkForwardFoldSummary(BaseModel):
    fold: int
    train_from: str
    train_to: str
    test_from: str
    test_to: str
    train_winner: str | None
    train_avg_rank: float | None
    strategy_metrics: BacktestMetrics | None
    benchmark_metrics: BacktestMetrics | None
    status: Literal["ok", "error"]
    error: str | None = None


class WalkForwardSummary(BaseModel):
    total_folds: int
    successful_folds: int
    most_frequent_winner: str | None
    average_oos_metrics: BacktestMetrics
    average_benchmark_metrics: BacktestMetrics
    folds: list[WalkForwardFoldSummary]


class StrategyEvaluationResponse(BaseModel):
    tool_name: Literal["run_strategy_evaluation"] = "run_strategy_evaluation"
    run_mode: Literal["single", "compare_variants", "parameter_sweep", "cross_preset", "walk_forward"]
    timestamp_utc: datetime
    tickers: list[str]
    parameters: dict[str, Any]
    benchmark: BenchmarkSummary | None = None
    single_run: StrategyConfigSummary | None = None
    compare_variants: list[StrategyConfigSummary] | None = None
    parameter_sweep: list[StrategyConfigSummary] | None = None
    cross_preset: CrossPresetSummary | None = None
    walk_forward: WalkForwardSummary | None = None
    warnings: list[str]


class ExplainRecommendationRequest(BaseModel):
    source: Literal["rank_assets", "strategy_evaluation"]
    ranking: RankAssetsResponse | None = None
    strategy_evaluation: StrategyEvaluationResponse | None = None


class ProfileConstraintApplied(BaseModel):
    constraint: str
    category: Literal["hard_block", "soft_caution", "preferred", "neutral"]
    detail: str


class PortfolioContextApplied(BaseModel):
    check: str
    status: Literal["context", "preferred", "caution", "block"]
    detail: str


class PortfolioPosition(BaseModel):
    ticker: str
    quantity: float = Field(ge=0)
    avg_cost: float | None = Field(default=None, ge=0)
    asset_type: str | None = None
    strategy_bucket: str | None = None
    entry_date: date | None = None
    notes: str | None = None
    target_role: str | None = None
    max_position_size_pct: float | None = Field(default=None, ge=0, le=1)
    thesis_ref: str | None = None


class LocalPortfolio(BaseModel):
    portfolio_name: str
    base_currency: str
    cash_available: float = Field(ge=0)
    positions: list[PortfolioPosition] = Field(default_factory=list)


class PositionContext(BaseModel):
    ticker: str
    is_held: bool
    quantity: float | None = None
    avg_cost: float | None = None
    estimated_value: float | None = None
    estimated_weight_pct: float | None = None
    exposure_group: str | None = None
    asset_type: str | None = None
    strategy_bucket: str | None = None


class RecommendationPayload(BaseModel):
    tool_name: Literal["explain_recommendation"] = "explain_recommendation"
    source: Literal["rank_assets", "strategy_evaluation"]
    recommended_entity_type: Literal["asset", "strategy_config"]
    recommended_entity: str | None
    top_deterministic_result: str | None = None
    summary: str
    why_preferred: list[str]
    invalidation_conditions: list[str]
    risks: list[str]
    caveats: list[str]
    supporting_metrics: dict[str, Any]
    profile_constraints_applied: list["ProfileConstraintApplied"] = Field(default_factory=list)
    portfolio_context_applied: list["PortfolioContextApplied"] = Field(default_factory=list)
    knowledge_sources_used: list["KnowledgeBaseMatch"] = Field(default_factory=list)
    recommendation_status: RecommendationStatus = "eligible"
    hard_conflicts: list[str] = Field(default_factory=list)
    soft_conflicts: list[str] = Field(default_factory=list)
    preference_matches: list[str] = Field(default_factory=list)
    constraint_summary: str = ""
    portfolio_decision_summary: str = ""
    recommended_action_type: RecommendedActionType | None = None
    position_context: PositionContext | None = None
    concentration_notes: list[str] = Field(default_factory=list)
    eligible_alternatives: list["EligibleAlternative"] = Field(default_factory=list)


class InvestorProfile(BaseModel):
    profile_name: str
    investment_objective: str
    time_horizon: str
    risk_tolerance: str
    max_acceptable_drawdown: float | None = Field(default=None, ge=0, le=1)
    preferred_assets: list[str] = Field(default_factory=list)
    disallowed_assets: list[str] = Field(default_factory=list)
    preferred_strategy_bias: str | None = None
    liquidity_needs: str | None = None
    notes: str | None = None


class KnowledgeBaseQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    doc_types: list[str] | None = None
    active_only: bool = True


class EligibleAlternative(BaseModel):
    entity: str
    reason: str
    recommendation_status: RecommendationStatus


class KnowledgeBaseMatch(BaseModel):
    title: str
    source: str
    snippet: str
    score: float
    doc_type: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    confidence_tier: Literal["high", "medium", "low"] = "low"


class KnowledgeBaseQueryResponse(BaseModel):
    tool_name: Literal["query_knowledge_base"] = "query_knowledge_base"
    backend: str
    query: str
    top_k: int
    matches: list[KnowledgeBaseMatch]
    warnings: list[str]


class CopilotChatSessionState(BaseModel):
    last_intent: Literal[
        "market_snapshot",
        "asset_ranking",
        "strategy_evaluation",
        "recommendation_explanation",
        "knowledge_base_query",
        "monitoring_check",
        "scorecard_check",
        "outcome_review",
        "comparative_validation",
        "shadow_portfolio",
        "paper_portfolio_nav",
        "forward_validation_pilot",
        "unclear",
    ] | None = None
    last_ranking: RankAssetsResponse | None = None
    last_strategy_evaluation: StrategyEvaluationResponse | None = None
    last_recommendation: RecommendationPayload | None = None


class CopilotChatRequest(BaseModel):
    user_query: str = Field(min_length=1)
    session_state: CopilotChatSessionState | None = None


class CopilotChatAnswer(BaseModel):
    headline: str
    summary: str
    bullets: list[str]
    deterministic_evidence_summary: str | None = None
    profile_decision_summary: str | None = None
    portfolio_decision_summary: str | None = None
    final_recommendation_summary: str | None = None
    why_this_is_or_is_not_actionable: str | None = None
    confidence_notes: list[str] = Field(default_factory=list)


class CopilotChatResponse(BaseModel):
    user_query: str
    detected_intent: Literal[
        "market_snapshot",
        "asset_ranking",
        "strategy_evaluation",
        "recommendation_explanation",
        "knowledge_base_query",
        "monitoring_check",
        "scorecard_check",
        "outcome_review",
        "comparative_validation",
        "shadow_portfolio",
        "paper_portfolio_nav",
        "forward_validation_pilot",
        "unclear",
    ]
    tools_used: list[str]
    answer: CopilotChatAnswer
    supporting_data: dict[str, Any]
    recommendation_status: RecommendationStatus | None = None
    profile_constraints_applied: list[ProfileConstraintApplied] = Field(default_factory=list)
    portfolio_context_applied: list[PortfolioContextApplied] = Field(default_factory=list)
    knowledge_sources_used: list[KnowledgeBaseMatch] = Field(default_factory=list)
    recommended_action_type: RecommendedActionType | None = None
    position_context: PositionContext | None = None
    concentration_notes: list[str] = Field(default_factory=list)
    eligible_alternatives: list[EligibleAlternative] = Field(default_factory=list)
    warnings: list[str]
    next_actions: list[str]
    session_state: CopilotChatSessionState
