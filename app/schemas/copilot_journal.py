"""Pydantic schemas for the local decision journal.

The journal stores one DecisionRecord per line in ``data/copilot/journal.jsonl``.
It is a local, deterministic, append-and-patch audit trail, not a database.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.copilot import (
    KnowledgeBaseMatch,
    PortfolioContextApplied,
    ProfileConstraintApplied,
    RecommendationStatus,
    RecommendedActionType,
)

ActionTaken = Literal["accepted", "rejected", "watchlist", "paper_only", "pending"]
JournalDetectedIntent = Literal[
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


class JournalRecommendationSnapshot(BaseModel):
    """Lean recommendation copy kept inside the journal for later review."""

    headline: str | None = None
    summary: str | None = None
    deterministic_evidence_summary: str | None = None
    profile_decision_summary: str | None = None
    portfolio_decision_summary: str | None = None
    final_recommendation_summary: str | None = None
    why_this_is_or_is_not_actionable: str | None = None
    recommended_entity: str | None = None
    recommended_entity_type: Literal["asset", "strategy_config"] | None = None
    why_preferred: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class DecisionCreateRequest(BaseModel):
    """Payload used to create a new journal record from a copilot response."""

    user_query: str = Field(min_length=1)
    detected_intent: JournalDetectedIntent
    top_deterministic_result: str | None = None
    final_recommendation: JournalRecommendationSnapshot | None = None
    recommendation_status: RecommendationStatus | None = None
    recommended_action_type: RecommendedActionType | None = None
    profile_constraints_applied: list[ProfileConstraintApplied] = Field(default_factory=list)
    knowledge_sources_used: list[KnowledgeBaseMatch] = Field(default_factory=list)
    portfolio_context_applied: list[PortfolioContextApplied] = Field(default_factory=list)
    portfolio_decision_summary: str | None = None
    action_taken: ActionTaken | None = None
    review_date: str | None = None
    outcome_notes: str | None = None


class DecisionRecord(BaseModel):
    """A complete journal entry stored as one JSON object per line."""

    decision_id: str
    timestamp: str
    user_query: str
    detected_intent: JournalDetectedIntent
    top_deterministic_result: str | None = None
    final_recommendation: JournalRecommendationSnapshot | None = None
    recommendation_status: RecommendationStatus | None = None
    recommended_action_type: RecommendedActionType | None = None
    profile_constraints_applied: list[ProfileConstraintApplied] = Field(default_factory=list)
    knowledge_sources_used: list[KnowledgeBaseMatch] = Field(default_factory=list)
    portfolio_context_applied: list[PortfolioContextApplied] = Field(default_factory=list)
    portfolio_decision_summary: str | None = None
    action_taken: ActionTaken | None = None
    action_taken_timestamp: str | None = None
    review_date: str | None = None
    outcome_notes: str | None = None


class DecisionPatch(BaseModel):
    """Partial update payload for an existing journal entry."""

    action_taken: ActionTaken | None = None
    action_taken_timestamp: str | None = None
    review_date: str | None = None
    outcome_notes: str | None = None


class JournalListResponse(BaseModel):
    """Response wrapper for journal listings."""

    entries: list[DecisionRecord]
    total: int
