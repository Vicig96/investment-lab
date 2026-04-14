"""Deterministic local shadow portfolio valuation over saved copilot decisions."""
from __future__ import annotations

from datetime import date, datetime, timezone
from statistics import median

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.candles import load_ohlcv_multi
from app.schemas.copilot_journal import DecisionRecord
from app.schemas.copilot_outcomes import OutcomeReviewRequest
from app.schemas.copilot_shadow_portfolio import (
    ShadowBenchmarkSummary,
    ShadowCohortDefinition,
    ShadowComparisonSummary,
    ShadowDateRange,
    ShadowPaperPosition,
    ShadowPaperSummary,
    ShadowPortfolioRequest,
    ShadowPortfolioResponse,
)
from app.services import copilot_journal as journal_service
from app.services import copilot_outcomes as outcome_service

_COHORT_LABELS = {
    "accepted": "Accepted decisions",
    "paper_only": "Paper-only decisions",
    "accepted_plus_paper_only": "Accepted plus paper-only decisions",
    "watchlist_later_actionable": "Watchlist ideas that later became actionable",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity_for_decision(record: DecisionRecord) -> str | None:
    if record.final_recommendation is not None and record.final_recommendation.recommended_entity:
        return record.final_recommendation.recommended_entity
    return record.top_deterministic_result


def _in_range(timestamp: str, date_from: str | None, date_to: str | None) -> bool:
    ts_date = timestamp[:10]
    if date_from and ts_date < date_from:
        return False
    if date_to and ts_date > date_to:
        return False
    return True


def _filtered_decisions(request: ShadowPortfolioRequest) -> list[DecisionRecord]:
    records = journal_service.list_decisions(
        date_from=request.date_from,
        date_to=request.date_to,
        limit=request.limit,
    )
    return sorted(records, key=lambda item: item.timestamp)


def _decision_date(record: DecisionRecord) -> date:
    return date.fromisoformat(record.timestamp[:10])


def _as_timestamp(value: date) -> str:
    return f"{value.isoformat()}T00:00:00+00:00"


def _select_decisions(
    request: ShadowPortfolioRequest,
    decisions: list[DecisionRecord],
) -> list[DecisionRecord]:
    if request.cohort_definition == "accepted":
        return [record for record in decisions if record.action_taken == "accepted"]
    if request.cohort_definition == "paper_only":
        return [record for record in decisions if record.action_taken == "paper_only"]
    if request.cohort_definition == "accepted_plus_paper_only":
        return [record for record in decisions if record.action_taken in {"accepted", "paper_only"}]

    watchlist_review = outcome_service.review_outcomes(
        OutcomeReviewRequest(
            date_from=request.date_from,
            date_to=request.date_to,
            action_taken="watchlist",
            limit=request.limit,
        )
    )
    actionable_ids = {
        entry.decision_id
        for entry in watchlist_review.entries
        if entry.watchlist_transition_status == "later_became_actionable"
    }
    return [record for record in decisions if record.decision_id in actionable_ids]


async def _load_price_history(
    session: AsyncSession,
    ticker: str,
    from_date: date,
    to_date: date | None,
) -> pd.DataFrame:
    normalized = ticker.upper()
    try:
        data = await load_ohlcv_multi(session, [normalized], from_date=from_date, to_date=to_date)
    except HTTPException:
        return pd.DataFrame()
    return data.get(normalized, pd.DataFrame())


def _build_supported_position(record: DecisionRecord, df: pd.DataFrame, to_date: date | None) -> ShadowPaperPosition:
    notes: list[str] = []
    decision_date = _decision_date(record)
    entry_candidates = df.loc[df.index >= decision_date]
    if entry_candidates.empty:
        return ShadowPaperPosition(
            decision_id=record.decision_id,
            entity=_entity_for_decision(record),
            decision_timestamp=record.timestamp,
            supported=False,
            support_notes=["No local daily close was available on or after the decision date for this entity."],
        )

    entry_date = entry_candidates.index[0]
    entry_price = float(entry_candidates.iloc[0]["close"])
    mark_candidates = entry_candidates if to_date is None else entry_candidates.loc[entry_candidates.index <= to_date]
    if mark_candidates.empty:
        return ShadowPaperPosition(
            decision_id=record.decision_id,
            entity=_entity_for_decision(record),
            decision_timestamp=record.timestamp,
            supported=False,
            support_notes=["No local daily close was available to mark this entity within the selected range."],
        )

    mark_date = mark_candidates.index[-1]
    mark_price = float(mark_candidates.iloc[-1]["close"])
    simple_return_pct = round(((mark_price - entry_price) / entry_price) * 100.0, 4)
    if mark_date == entry_date:
        notes.append("Only one local daily close was available after the decision date, so the paper mark equals the assumed entry snapshot.")

    return ShadowPaperPosition(
        decision_id=record.decision_id,
        entity=_entity_for_decision(record),
        decision_timestamp=record.timestamp,
        assumed_entry_timestamp=_as_timestamp(entry_date),
        assumed_entry_price=entry_price,
        latest_mark_timestamp=_as_timestamp(mark_date),
        latest_mark_price=mark_price,
        supported=True,
        support_notes=notes,
        simple_return_pct=simple_return_pct,
    )


async def _build_position(
    session: AsyncSession,
    record: DecisionRecord,
    to_date: date | None,
) -> ShadowPaperPosition:
    entity = _entity_for_decision(record)
    if not entity:
        return ShadowPaperPosition(
            decision_id=record.decision_id,
            entity=None,
            decision_timestamp=record.timestamp,
            supported=False,
            support_notes=["No entity was stored on this decision, so a shadow position could not be valued."],
        )

    df = await _load_price_history(session, entity, _decision_date(record), to_date)
    if df.empty:
        return ShadowPaperPosition(
            decision_id=record.decision_id,
            entity=entity,
            decision_timestamp=record.timestamp,
            supported=False,
            support_notes=["No local price history was available for this entity after the decision date."],
        )
    return _build_supported_position(record, df, to_date)


async def _build_benchmark_summary(
    session: AsyncSession,
    benchmark_ticker: str | None,
    supported_positions: list[ShadowPaperPosition],
) -> ShadowBenchmarkSummary:
    normalized_benchmark = benchmark_ticker.upper() if benchmark_ticker else None
    if not benchmark_ticker:
        return ShadowBenchmarkSummary(
            benchmark_ticker=None,
            supported=False,
            support_notes=["No benchmark ticker was requested for this shadow portfolio review."],
        )
    if not supported_positions:
        return ShadowBenchmarkSummary(
            benchmark_ticker=normalized_benchmark,
            supported=False,
            support_notes=["No supported paper positions were available, so a benchmark window could not be formed."],
        )

    start_date = min(date.fromisoformat(item.assumed_entry_timestamp[:10]) for item in supported_positions if item.assumed_entry_timestamp)
    end_date = max(date.fromisoformat(item.latest_mark_timestamp[:10]) for item in supported_positions if item.latest_mark_timestamp)
    df = await _load_price_history(session, normalized_benchmark, start_date, end_date)
    if df.empty:
        return ShadowBenchmarkSummary(
            benchmark_ticker=normalized_benchmark,
            supported=False,
            support_notes=["No local benchmark price history was available for the shadow portfolio window."],
        )

    entry_candidates = df.loc[df.index >= start_date]
    mark_candidates = df.loc[df.index <= end_date]
    if entry_candidates.empty or mark_candidates.empty:
        return ShadowBenchmarkSummary(
            benchmark_ticker=normalized_benchmark,
            supported=False,
            support_notes=["Benchmark price history did not cover the needed entry or mark dates."],
        )

    entry_date = entry_candidates.index[0]
    mark_date = mark_candidates.index[-1]
    entry_price = float(entry_candidates.iloc[0]["close"])
    mark_price = float(mark_candidates.iloc[-1]["close"])
    simple_return_pct = round(((mark_price - entry_price) / entry_price) * 100.0, 4)
    notes: list[str] = []
    if mark_date == entry_date:
        notes.append("Only one local benchmark close was available for the matched window.")

    return ShadowBenchmarkSummary(
        benchmark_ticker=normalized_benchmark,
        supported=True,
        assumed_entry_timestamp=_as_timestamp(entry_date),
        assumed_entry_price=entry_price,
        latest_mark_timestamp=_as_timestamp(mark_date),
        latest_mark_price=mark_price,
        simple_return_pct=simple_return_pct,
        support_notes=notes,
    )


def _paper_summary(positions: list[ShadowPaperPosition]) -> ShadowPaperSummary:
    supported = [item for item in positions if item.supported and item.simple_return_pct is not None]
    returns = [item.simple_return_pct for item in supported]
    return ShadowPaperSummary(
        total_positions=len(positions),
        supported_positions=len(supported),
        unsupported_positions=len(positions) - len(supported),
        average_simple_return_pct=round(sum(returns) / len(returns), 4) if returns else None,
        median_simple_return_pct=round(float(median(returns)), 4) if returns else None,
        equal_weight_simple_return_pct=round(sum(returns) / len(returns), 4) if returns else None,
        positive_count=sum(1 for value in returns if value > 0),
        negative_count=sum(1 for value in returns if value < 0),
    )


def _comparison_summary(
    cohort_key: str,
    paper_summary: ShadowPaperSummary,
    benchmark_summary: ShadowBenchmarkSummary,
) -> ShadowComparisonSummary:
    notes: list[str] = [
        "This is a paper comparison based on local daily closes only. It does not model fills, slippage, fees, or execution quality."
    ]
    if paper_summary.equal_weight_simple_return_pct is None:
        return ShadowComparisonSummary(
            benchmark_comparison_supported=False,
            benchmark_ticker=benchmark_summary.benchmark_ticker,
            cohort_equal_weight_simple_return_pct=None,
            benchmark_simple_return_pct=benchmark_summary.simple_return_pct,
            interpretation="The shadow cohort could not be compared because no supported paper positions had enough local price history.",
            notes=notes,
        )
    if not benchmark_summary.supported or benchmark_summary.simple_return_pct is None:
        return ShadowComparisonSummary(
            benchmark_comparison_supported=False,
            benchmark_ticker=benchmark_summary.benchmark_ticker,
            cohort_equal_weight_simple_return_pct=paper_summary.equal_weight_simple_return_pct,
            benchmark_simple_return_pct=None,
            interpretation="A benchmark comparison was not supported by the available local data.",
            notes=notes + benchmark_summary.support_notes,
        )

    cohort_return = paper_summary.equal_weight_simple_return_pct
    benchmark_return = benchmark_summary.simple_return_pct
    if cohort_return == benchmark_return:
        interpretation = (
            f"The supported { _COHORT_LABELS[cohort_key].lower() } marked roughly in line with "
            f"{benchmark_summary.benchmark_ticker} over the same broad local window."
        )
    elif cohort_return > benchmark_return:
        interpretation = (
            f"The supported { _COHORT_LABELS[cohort_key].lower() } currently mark above "
            f"{benchmark_summary.benchmark_ticker} on a simple-return basis over the same broad local window."
        )
    else:
        interpretation = (
            f"The supported { _COHORT_LABELS[cohort_key].lower() } currently mark below "
            f"{benchmark_summary.benchmark_ticker} on a simple-return basis over the same broad local window."
        )

    return ShadowComparisonSummary(
        benchmark_comparison_supported=True,
        benchmark_ticker=benchmark_summary.benchmark_ticker,
        cohort_equal_weight_simple_return_pct=cohort_return,
        benchmark_simple_return_pct=benchmark_return,
        interpretation=interpretation,
        notes=notes,
    )


async def build_shadow_portfolio(
    session: AsyncSession,
    request: ShadowPortfolioRequest,
) -> ShadowPortfolioResponse:
    warnings = [
        "Paper entry uses the first local daily close on or after the decision date, and marks use the latest local daily close in range.",
        "Shadow portfolio results are paper estimates only. They do not infer fills, slippage, fees, or broker execution quality.",
    ]
    missing_data_notes: list[str] = []

    decisions = _filtered_decisions(request)
    selected = _select_decisions(request, decisions)
    if not selected:
        note = "No journal decisions matched the selected shadow cohort and date range."
        warnings.append(note)
        missing_data_notes.append(note)

    to_date = date.fromisoformat(request.date_to) if request.date_to else None
    paper_positions = [
        await _build_position(session, record, to_date)
        for record in selected
    ]

    for position in paper_positions:
        for note in position.support_notes:
            if note not in missing_data_notes:
                missing_data_notes.append(note)

    paper_summary = _paper_summary(paper_positions)
    supported = [item for item in paper_positions if item.supported]
    benchmark_summary = await _build_benchmark_summary(session, request.benchmark_ticker, supported)
    for note in benchmark_summary.support_notes:
        if note not in missing_data_notes:
            missing_data_notes.append(note)

    comparison_summary = _comparison_summary(request.cohort_definition, paper_summary, benchmark_summary)
    for note in comparison_summary.notes:
        if note not in warnings:
            warnings.append(note)

    range_label = "all available local history"
    if request.date_from or request.date_to:
        range_label = f"{request.date_from or 'start'} to {request.date_to or 'latest'}"

    return ShadowPortfolioResponse(
        generated_at=_now_utc(),
        date_range=ShadowDateRange(
            start=request.date_from,
            end=request.date_to,
            label=range_label,
        ),
        cohort_definition=ShadowCohortDefinition(
            cohort_key=request.cohort_definition,
            label=_COHORT_LABELS[request.cohort_definition],
            weighting="equal_weight",
            benchmark_ticker=request.benchmark_ticker.upper() if request.benchmark_ticker else None,
        ),
        paper_positions=paper_positions,
        supported_positions=paper_summary.supported_positions,
        unsupported_positions=paper_summary.unsupported_positions,
        paper_summary=paper_summary,
        benchmark_summary=benchmark_summary,
        comparison_summary=comparison_summary,
        warnings=warnings,
        missing_data_notes=missing_data_notes,
    )
