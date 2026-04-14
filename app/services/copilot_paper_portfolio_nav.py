"""Deterministic local paper portfolio NAV builder over saved copilot decisions."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.candles import load_ohlcv_multi
from app.schemas.copilot_monitoring import MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_paper_portfolio_nav import (
    PaperPortfolioAssumptions,
    PaperPortfolioBenchmarkSummary,
    PaperPortfolioComparisonSummary,
    PaperPortfolioCohortDefinition,
    PaperPortfolioCountItem,
    PaperPortfolioDateRange,
    PaperPortfolioHoldExitPolicySummary,
    PaperPortfolioNavPoint,
    PaperPortfolioNavRequest,
    PaperPortfolioNavResponse,
    PaperPortfolioNavSummary,
    PaperPortfolioPositionSummary,
)
from app.services import copilot_monitoring as monitoring_service
from app.services import copilot_outcomes as outcome_service
from app.services import copilot_shadow_portfolio as shadow_service

_USABLE_STATUSES = {
    "eligible",
    "eligible_with_cautions",
    "eligible_new_position",
    "eligible_add_to_existing",
}
_NEGATIVE_FINDING_TYPES = {
    "holding_rule_violation",
    "holding_drawdown_breach",
    "best_eligible_asset_changed",
    "thesis_support_missing",
    "portfolio_concentration_warning",
    "missing_data",
}
_EXIT_PRIORITY = {"hard_conflict": 0, "negative_signal": 1, "deterioration": 2, "replacement": 3}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_timestamp(value: date) -> str:
    return f"{value.isoformat()}T00:00:00+00:00"


def _as_date(timestamp: str | None) -> date | None:
    return date.fromisoformat(timestamp[:10]) if timestamp else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def _is_usable(status: str | None) -> bool:
    return status in _USABLE_STATUSES


def _is_hard_conflict_decision(record) -> bool:
    if record.recommendation_status in {"rejected_by_profile", "rejected_by_portfolio_constraints"}:
        return True
    return any(item.category == "hard_block" for item in record.profile_constraints_applied)


async def _load_price_history(session: AsyncSession, ticker: str, from_date: date, to_date: date | None) -> pd.DataFrame:
    try:
        data = await load_ohlcv_multi(session, [ticker.upper()], from_date=from_date, to_date=to_date)
    except HTTPException:
        return pd.DataFrame()
    return data.get(ticker.upper(), pd.DataFrame())


def _last_close_on_or_before(df: pd.DataFrame, current_date: date) -> float | None:
    candidates = df.loc[df.index <= current_date]
    if candidates.empty:
        return None
    return float(candidates.iloc[-1]["close"])


def _max_drawdown_pct(points: list[PaperPortfolioNavPoint]) -> float | None:
    if not points:
        return None
    peak = points[0].portfolio_value
    max_drawdown = 0.0
    for point in points:
        if point.portfolio_value > peak:
            peak = point.portfolio_value
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - point.portfolio_value) / peak * 100.0)
    return _round(max_drawdown)


def _all_findings() -> list[MonitoringFinding]:
    findings: list[MonitoringFinding] = []
    for obj in monitoring_service._read_jsonl(monitoring_service.FINDINGS_PATH):
        try:
            findings.append(MonitoringFinding.model_validate(obj))
        except Exception:
            continue
    findings.sort(key=lambda item: item.timestamp)
    return findings


def _all_snapshots() -> list[MonitoringSnapshotRecord]:
    snapshots: list[MonitoringSnapshotRecord] = []
    for obj in monitoring_service._read_jsonl(monitoring_service.SNAPSHOTS_PATH):
        try:
            snapshots.append(MonitoringSnapshotRecord.model_validate(obj))
        except Exception:
            continue
    snapshots.sort(key=lambda item: item.timestamp)
    return snapshots


def _asset_state(snapshot: MonitoringSnapshotRecord, entity: str):
    return next((item for item in snapshot.monitored_assets if item.ticker == entity), None)


def _holding_state(snapshot: MonitoringSnapshotRecord, entity: str):
    return next((item for item in snapshot.holdings if item.ticker == entity), None)


def _supported_exit_for_trigger(*, trigger_type: str, trigger_timestamp: str, df: pd.DataFrame, to_date: date | None) -> dict[str, Any]:
    trigger_date = _as_date(trigger_timestamp)
    if trigger_date is None:
        return {
            "exit_policy_status": "unsupported_exit_decision",
            "exit_trigger_type": trigger_type,
            "exit_trigger_timestamp": trigger_timestamp,
            "supported_exit": False,
            "notes": ["Exit trigger timestamp could not be parsed from the local evidence."],
        }
    candidates = df.loc[df.index >= trigger_date]
    if to_date is not None:
        candidates = candidates.loc[candidates.index <= to_date]
    if candidates.empty:
        return {
            "exit_policy_status": "unsupported_exit_decision",
            "exit_trigger_type": trigger_type,
            "exit_trigger_timestamp": trigger_timestamp,
            "supported_exit": False,
            "notes": ["An exit trigger was found, but no local daily close was available on or after the trigger date within the selected range."],
        }
    exit_date = candidates.index[0]
    exit_price = float(candidates.iloc[0]["close"])
    return {
        "exit_policy_status": {
            "replacement": "exited_on_replacement",
            "deterioration": "exited_on_deterioration",
            "hard_conflict": "exited_on_hard_conflict",
            "negative_signal": "exited_on_negative_signal",
        }[trigger_type],
        "exit_trigger_type": trigger_type,
        "exit_trigger_timestamp": trigger_timestamp,
        "supported_exit": True,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "notes": [],
    }


def _find_exit_trigger(
    *,
    record,
    entity: str,
    df: pd.DataFrame,
    later_selected: list[dict[str, Any]],
    all_decisions,
    findings: list[MonitoringFinding],
    snapshots: list[MonitoringSnapshotRecord],
    to_date: date | None,
) -> dict[str, Any]:
    triggers: list[tuple[str, str, str]] = []
    replacement = next((item for item in later_selected if item["entity"] == entity and item["record"].timestamp > record.timestamp), None)
    if replacement is not None:
        triggers.append((replacement["record"].timestamp, "replacement", "A later accepted or paper-followed decision in the same entity was treated as a replacement trigger."))

    later_same_entity = [
        item
        for item in all_decisions
        if item.timestamp > record.timestamp and shadow_service._entity_for_decision(item) == entity
    ]
    hard_conflict_decision = next((item for item in later_same_entity if _is_hard_conflict_decision(item)), None)
    if hard_conflict_decision is not None:
        triggers.append((hard_conflict_decision.timestamp, "hard_conflict", "A later saved decision for this entity recorded a hard profile or portfolio conflict."))

    for snapshot in snapshots:
        if snapshot.timestamp <= record.timestamp:
            continue
        state = _asset_state(snapshot, entity)
        holding = _holding_state(snapshot, entity)
        if state is None and holding is None:
            continue
        hard_conflicts = [*(state.hard_conflicts if state else []), *(holding.hard_conflicts if holding else [])]
        if hard_conflicts:
            triggers.append((snapshot.timestamp, "hard_conflict", "A later monitoring snapshot showed a hard conflict for this entity."))
            break

    for snapshot in snapshots:
        if snapshot.timestamp <= record.timestamp:
            continue
        state = _asset_state(snapshot, entity)
        if state is None or state.hard_conflicts:
            continue
        if not _is_usable(state.recommendation_status):
            triggers.append((snapshot.timestamp, "deterioration", "A later monitoring snapshot showed this entity as no longer locally actionable."))
            break

    negative_finding = next(
        (
            finding
            for finding in findings
            if finding.timestamp > record.timestamp
            and finding.entity == entity
            and finding.severity in {"warning", "critical"}
            and finding.finding_type in _NEGATIVE_FINDING_TYPES
        ),
        None,
    )
    if negative_finding is not None:
        triggers.append((negative_finding.timestamp, "negative_signal", "A later warning or critical monitoring finding for this entity was treated as a negative exit signal."))

    if not triggers:
        return {"exit_policy_status": "hold_to_window_end", "supported_exit": None, "notes": []}

    trigger_timestamp, trigger_type, trigger_note = min(triggers, key=lambda item: (item[0], _EXIT_PRIORITY[item[1]]))
    exit_decision = _supported_exit_for_trigger(trigger_type=trigger_type, trigger_timestamp=trigger_timestamp, df=df, to_date=to_date)
    exit_decision["notes"] = [trigger_note, *exit_decision["notes"]]
    return exit_decision


def _planned_position_summary(item: dict[str, Any], allocation_per_position: float) -> PaperPortfolioPositionSummary:
    record = item["record"]
    allocated = allocation_per_position
    entry_price = item["entry_price"]
    units = allocated / entry_price if entry_price > 0 else 0.0
    latest_value = units * item["latest_mark_price"]
    latest_return = ((latest_value - allocated) / allocated * 100.0) if allocated > 0 else None
    exit_info = item.get("exit_info", {})

    lifecycle_status = "active"
    current_mark_timestamp = _as_timestamp(item["latest_mark_date"])
    current_mark_price = _round(item["latest_mark_price"])
    current_value = _round(latest_value)
    simple_return_pct = _round(latest_return)
    realized_return = None

    if exit_info.get("supported_exit") and exit_info.get("exit_date") is not None:
        lifecycle_status = "exited"
        exit_value = units * float(exit_info["exit_price"])
        realized_return = ((exit_value - allocated) / allocated * 100.0) if allocated > 0 else None
        current_mark_timestamp = _as_timestamp(exit_info["exit_date"])
        current_mark_price = _round(exit_info["exit_price"])
        current_value = _round(exit_value)
        simple_return_pct = _round(realized_return)

    return PaperPortfolioPositionSummary(
        decision_id=record.decision_id,
        entity=item["entity"],
        assumed_entry_timestamp=_as_timestamp(item["entry_date"]),
        assumed_entry_price=_round(entry_price),
        exit_policy_status=exit_info.get("exit_policy_status", "hold_to_window_end"),
        exit_trigger_type=exit_info.get("exit_trigger_type"),
        exit_trigger_timestamp=exit_info.get("exit_trigger_timestamp"),
        assumed_exit_timestamp=_as_timestamp(exit_info["exit_date"]) if exit_info.get("exit_date") is not None else None,
        assumed_exit_price=_round(exit_info.get("exit_price")),
        realized_or_closed_simple_return_pct=_round(realized_return),
        current_mark_timestamp=current_mark_timestamp,
        current_mark_price=current_mark_price,
        allocated_capital=_round(allocated) or 0.0,
        current_value=current_value,
        simple_return_pct=simple_return_pct,
        supported=True,
        supported_exit=exit_info.get("supported_exit"),
        support_notes=item.get("notes", []),
        lifecycle_notes=exit_info.get("notes", []),
        lifecycle_status=lifecycle_status,
    )


def _nav_dates(open_positions: list[dict[str, Any]], request: PaperPortfolioNavRequest) -> list[date]:
    nav_dates = sorted(
        {
            current_date
            for item in open_positions
            for current_date in item["df"].index.tolist()
            if current_date >= item["entry_date"]
        }
    )
    if open_positions:
        nav_start = date.fromisoformat(request.date_from) if request.date_from else min(item["entry_date"] for item in open_positions)
        nav_end = date.fromisoformat(request.date_to) if request.date_to else max(item["latest_mark_date"] for item in open_positions)
        nav_dates = sorted({*nav_dates, nav_start, nav_end})
    return nav_dates


def _build_nav_path(*, request: PaperPortfolioNavRequest, open_positions: list[dict[str, Any]], apply_exit_policy: bool) -> list[PaperPortfolioNavPoint]:
    nav_points: list[PaperPortfolioNavPoint] = []
    for current_date in _nav_dates(open_positions, request):
        cash = request.initial_capital
        invested_value = 0.0
        active_count = 0
        for item in open_positions:
            if item["entry_date"] > current_date:
                continue
            allocated = item["allocated_capital"]
            exit_info = item.get("exit_info", {})
            exit_date = exit_info.get("exit_date")
            if apply_exit_policy and exit_info.get("supported_exit") and exit_date is not None and current_date >= exit_date:
                cash -= allocated
                cash += item["units"] * float(exit_info["exit_price"])
                continue
            cash -= allocated
            last_close = _last_close_on_or_before(item["df"], current_date)
            if last_close is None:
                continue
            invested_value += item["units"] * last_close
            active_count += 1
        nav_points.append(
            PaperPortfolioNavPoint(
                date=current_date.isoformat(),
                portfolio_value=_round(cash + invested_value) or 0.0,
                cash=_round(cash) or 0.0,
                invested_value=_round(invested_value) or 0.0,
                active_position_count=active_count,
            )
        )
    return nav_points


async def _build_benchmark_summary(session: AsyncSession, request: PaperPortfolioNavRequest, nav_points: list[PaperPortfolioNavPoint]) -> PaperPortfolioBenchmarkSummary:
    benchmark_ticker = request.benchmark_ticker.upper() if request.benchmark_ticker else None
    if not benchmark_ticker:
        return PaperPortfolioBenchmarkSummary(benchmark_ticker=None, supported=False, support_notes=["No benchmark ticker was requested for this paper portfolio review."])
    if not nav_points:
        return PaperPortfolioBenchmarkSummary(benchmark_ticker=benchmark_ticker, supported=False, support_notes=["No supported portfolio NAV window was available, so benchmark comparison could not be formed."])

    benchmark_df = await _load_price_history(session, benchmark_ticker, date.fromisoformat(nav_points[0].date), date.fromisoformat(nav_points[-1].date))
    if benchmark_df.empty:
        return PaperPortfolioBenchmarkSummary(benchmark_ticker=benchmark_ticker, supported=False, support_notes=["No local benchmark price history was available for the paper portfolio window."])

    start_date = date.fromisoformat(nav_points[0].date)
    end_date = date.fromisoformat(nav_points[-1].date)
    entry_candidates = benchmark_df.loc[benchmark_df.index >= start_date]
    mark_candidates = benchmark_df.loc[benchmark_df.index <= end_date]
    if entry_candidates.empty or mark_candidates.empty:
        return PaperPortfolioBenchmarkSummary(benchmark_ticker=benchmark_ticker, supported=False, support_notes=["Benchmark price history did not cover the needed portfolio window."])

    entry_date = entry_candidates.index[0]
    mark_date = mark_candidates.index[-1]
    entry_price = float(entry_candidates.iloc[0]["close"])
    mark_price = float(mark_candidates.iloc[-1]["close"])
    simple_return_pct = ((mark_price - entry_price) / entry_price) * 100.0
    return PaperPortfolioBenchmarkSummary(
        benchmark_ticker=benchmark_ticker,
        supported=True,
        assumed_entry_timestamp=_as_timestamp(entry_date),
        assumed_entry_price=_round(entry_price),
        latest_mark_timestamp=_as_timestamp(mark_date),
        latest_mark_price=_round(mark_price),
        simple_return_pct=_round(simple_return_pct),
        ending_value=_round(request.initial_capital * (1 + simple_return_pct / 100.0)),
        support_notes=[],
    )


def _comparison_summary(*, request: PaperPortfolioNavRequest, ending_value: float, hold_only_ending_value: float | None, nav_summary: PaperPortfolioNavSummary, benchmark_summary: PaperPortfolioBenchmarkSummary) -> PaperPortfolioComparisonSummary:
    notes = ["Benchmark comparisons use the same broad local window as the generated paper NAV path and simple-return math only."]
    policy_difference = _round(ending_value - hold_only_ending_value) if request.apply_exit_policy and hold_only_ending_value is not None else None
    if request.apply_exit_policy and hold_only_ending_value is not None and policy_difference is not None:
        if policy_difference > 0:
            notes.append("The explicit exit policy ended above the hold-to-window-end baseline on the same local data.")
        elif policy_difference < 0:
            notes.append("The explicit exit policy ended below the hold-to-window-end baseline on the same local data.")
        else:
            notes.append("The explicit exit policy finished in line with the hold-to-window-end baseline on the same local data.")

    if nav_summary.total_portfolio_simple_return_pct is None:
        return PaperPortfolioComparisonSummary(
            benchmark_comparison_supported=False,
            benchmark_ticker=benchmark_summary.benchmark_ticker,
            portfolio_simple_return_pct=None,
            benchmark_simple_return_pct=benchmark_summary.simple_return_pct,
            hold_to_window_end_ending_value=_round(hold_only_ending_value),
            exit_policy_ending_value_difference=policy_difference,
            interpretation="The paper portfolio could not be compared because no supported NAV path was available.",
            notes=notes,
        )

    interpretation = "A benchmark comparison was not supported by the available local data."
    if benchmark_summary.supported and benchmark_summary.simple_return_pct is not None:
        portfolio_return = nav_summary.total_portfolio_simple_return_pct
        benchmark_return = benchmark_summary.simple_return_pct
        if portfolio_return == benchmark_return:
            interpretation = f"The paper portfolio tracked roughly in line with {benchmark_summary.benchmark_ticker} over the same broad local window."
        elif portfolio_return > benchmark_return:
            interpretation = f"The paper portfolio currently sits above {benchmark_summary.benchmark_ticker} on a simple local NAV basis over the same broad window."
        else:
            interpretation = f"The paper portfolio currently sits below {benchmark_summary.benchmark_ticker} on a simple local NAV basis over the same broad window."
    else:
        notes.extend(benchmark_summary.support_notes)

    return PaperPortfolioComparisonSummary(
        benchmark_comparison_supported=bool(benchmark_summary.supported and benchmark_summary.simple_return_pct is not None),
        benchmark_ticker=benchmark_summary.benchmark_ticker,
        portfolio_simple_return_pct=nav_summary.total_portfolio_simple_return_pct,
        benchmark_simple_return_pct=benchmark_summary.simple_return_pct,
        hold_to_window_end_ending_value=_round(hold_only_ending_value),
        exit_policy_ending_value_difference=policy_difference,
        interpretation=interpretation,
        notes=notes,
    )


async def build_paper_portfolio_nav(session: AsyncSession, request: PaperPortfolioNavRequest) -> PaperPortfolioNavResponse:
    warnings: list[str] = [
        "Paper entries use the first local daily close on or after the decision date.",
        "Cash is reduced only when a supported paper position actually opens.",
        "Paper portfolio NAV is a cautious local estimate only. It does not model fills, slippage, fees, taxes, or broker execution quality.",
    ]
    missing_data_notes: list[str] = []

    decisions = shadow_service._filtered_decisions(request)  # type: ignore[arg-type]
    selected = shadow_service._select_decisions(request, decisions)  # type: ignore[arg-type]
    if not selected:
        note = "No journal decisions matched the selected paper portfolio cohort and date range."
        warnings.append(note)
        missing_data_notes.append(note)

    to_date = date.fromisoformat(request.date_to) if request.date_to else None
    prepared: list[dict[str, Any]] = []
    for record in selected:
        entity = shadow_service._entity_for_decision(record)
        if not entity:
            prepared.append({"record": record, "entity": None, "supported": False, "notes": ["No entity was stored on this decision, so no paper position could be opened."]})
            continue
        from_date = shadow_service._decision_date(record)
        df = await _load_price_history(session, entity, from_date, to_date)
        if df.empty:
            prepared.append({"record": record, "entity": entity, "supported": False, "notes": ["No local price history was available for this entity after the decision date."]})
            continue
        entry_candidates = df.loc[df.index >= from_date]
        if entry_candidates.empty:
            prepared.append({"record": record, "entity": entity, "supported": False, "notes": ["No local daily close was available on or after the decision date for this entity."]})
            continue
        mark_candidates = df if to_date is None else df.loc[df.index <= to_date]
        if mark_candidates.empty:
            prepared.append({"record": record, "entity": entity, "supported": False, "notes": ["No local daily close was available to mark this entity within the selected range."]})
            continue
        prepared.append(
            {
                "record": record,
                "entity": entity,
                "supported": True,
                "df": df,
                "entry_date": entry_candidates.index[0],
                "entry_price": float(entry_candidates.iloc[0]["close"]),
                "latest_mark_date": mark_candidates.index[-1],
                "latest_mark_price": float(mark_candidates.iloc[-1]["close"]),
                "notes": [],
            }
        )

    prepared.sort(key=lambda item: (item.get("entry_date") or date.max, item["record"].timestamp, item["record"].decision_id))
    supported_items = [item for item in prepared if item["supported"]]
    unsupported_candidates = [item for item in prepared if not item["supported"]]
    policy_notes: list[str] = []

    if request.apply_exit_policy:
        warnings.append("Paper exit policy v1 is enabled: positions may exit on supported replacement, deterioration, hard-conflict, or negative-signal evidence.")
        findings = _all_findings()
        snapshots = _all_snapshots()
        all_decisions = outcome_service._all_decisions()
        if not snapshots:
            note = "No monitoring snapshots were available for paper exit policy checks, so deterioration and hard-conflict exits may be limited."
            warnings.append(note)
            missing_data_notes.append(note)
        if not findings:
            note = "No monitoring findings were available for paper exit policy checks, so negative-signal exits may be limited."
            warnings.append(note)
            missing_data_notes.append(note)
        policy_notes.append("Replacement checks use later decisions in the same entity only. Same strategy-bucket replacement is not evaluated in v1 because that bucket is not stored on journal entries.")
        for item in supported_items:
            item["exit_info"] = _find_exit_trigger(
                record=item["record"],
                entity=item["entity"],
                df=item["df"],
                later_selected=supported_items,
                all_decisions=all_decisions,
                findings=findings,
                snapshots=snapshots,
                to_date=to_date,
            )
    else:
        policy_notes.append("Exit policy v1 was not applied, so supported positions hold to the selected window end.")
        for item in supported_items:
            item["exit_info"] = {"exit_policy_status": "hold_to_window_end", "supported_exit": None, "notes": []}

    openable_candidates: list[dict[str, Any]] = []
    inactive_duplicates: list[dict[str, Any]] = []
    active_entity_exits: dict[str, date | None] = {}
    for item in supported_items:
        entity = item["entity"]
        entry_date = item["entry_date"]
        active_exit_date = active_entity_exits.get(entity)
        if active_exit_date is not None and entry_date < active_exit_date:
            item["supported"] = False
            item["notes"] = ["Duplicate concurrent entry was skipped because this entity was already active before the earlier supported exit date."]
            inactive_duplicates.append(item)
            continue
        if active_exit_date is None and entity in active_entity_exits:
            item["supported"] = False
            item["notes"] = ["Duplicate concurrent entry was skipped because the earlier active position in this entity did not have a supported exit date."]
            inactive_duplicates.append(item)
            continue
        openable_candidates.append(item)
        exit_info = item.get("exit_info", {})
        active_entity_exits[entity] = exit_info.get("exit_date") if request.apply_exit_policy and exit_info.get("supported_exit") else None

    allocation_per_position = request.initial_capital / len(openable_candidates) if openable_candidates else 0.0
    position_summaries: list[PaperPortfolioPositionSummary] = []
    open_positions: list[dict[str, Any]] = []
    active_position_ids: list[str] = []
    closed_or_inactive_position_ids: list[str] = []

    for item in openable_candidates:
        item["allocated_capital"] = allocation_per_position
        item["units"] = allocation_per_position / item["entry_price"] if item["entry_price"] > 0 else 0.0
        summary = _planned_position_summary(item, allocation_per_position)
        position_summaries.append(summary)
        open_positions.append(item)
        if summary.lifecycle_status == "active":
            active_position_ids.append(summary.decision_id)
        else:
            closed_or_inactive_position_ids.append(summary.decision_id)

    for item in [*unsupported_candidates, *inactive_duplicates]:
        record = item["record"]
        is_duplicate = bool(item.get("notes")) and "Duplicate concurrent entry" in item["notes"][0]
        position_summaries.append(
            PaperPortfolioPositionSummary(
                decision_id=record.decision_id,
                entity=item.get("entity"),
                allocated_capital=0.0,
                current_value=None,
                supported=False,
                supported_exit=None,
                support_notes=item["notes"],
                lifecycle_notes=[],
                lifecycle_status="inactive_duplicate" if is_duplicate else "unsupported_missing_data",
                exit_policy_status="unsupported_exit_decision" if request.apply_exit_policy and not is_duplicate else "hold_to_window_end",
            )
        )
        closed_or_inactive_position_ids.append(record.decision_id)

    for summary in position_summaries:
        for note in [*summary.support_notes, *summary.lifecycle_notes]:
            if note not in missing_data_notes:
                missing_data_notes.append(note)

    nav_points = _build_nav_path(request=request, open_positions=open_positions, apply_exit_policy=request.apply_exit_policy)
    if not nav_points and open_positions:
        note = "Supported positions were found, but no valuation dates could be formed from the available local price history."
        warnings.append(note)
        missing_data_notes.append(note)

    hold_only_nav_points = _build_nav_path(request=request, open_positions=open_positions, apply_exit_policy=False) if request.apply_exit_policy else nav_points
    ending_value = nav_points[-1].portfolio_value if nav_points else request.initial_capital
    cash_remaining = nav_points[-1].cash if nav_points else request.initial_capital
    hold_only_ending_value = hold_only_nav_points[-1].portfolio_value if hold_only_nav_points else request.initial_capital

    supported_returns = [summary.simple_return_pct for summary in position_summaries if summary.supported and summary.simple_return_pct is not None]
    nav_summary = PaperPortfolioNavSummary(
        total_positions_entered=len(openable_candidates),
        supported_positions=len(openable_candidates),
        unsupported_positions=len(position_summaries) - len(openable_candidates),
        total_portfolio_simple_return_pct=_round(((ending_value - request.initial_capital) / request.initial_capital) * 100.0) if nav_points else None,
        max_paper_drawdown_pct=_max_drawdown_pct(nav_points),
        average_position_simple_return_pct=_round(sum(supported_returns) / len(supported_returns)) if supported_returns else None,
        median_position_simple_return_pct=_round(float(median(supported_returns))) if supported_returns else None,
        positive_positions_count=sum(1 for value in supported_returns if value > 0),
        negative_positions_count=sum(1 for value in supported_returns if value < 0),
    )

    benchmark_summary = await _build_benchmark_summary(session, request, nav_points)
    for note in benchmark_summary.support_notes:
        if note not in missing_data_notes:
            missing_data_notes.append(note)
    comparison_summary = _comparison_summary(
        request=request,
        ending_value=ending_value,
        hold_only_ending_value=hold_only_ending_value,
        nav_summary=nav_summary,
        benchmark_summary=benchmark_summary,
    )

    exit_distribution_counter = Counter(summary.exit_policy_status for summary in position_summaries if summary.supported)
    exit_reason_distribution = [PaperPortfolioCountItem(item=item, count=count) for item, count in sorted(exit_distribution_counter.items())]
    unsupported_exit_count = sum(1 for summary in position_summaries if summary.supported and summary.exit_policy_status == "unsupported_exit_decision")
    exited_positions_count = sum(1 for summary in position_summaries if summary.lifecycle_status == "exited")
    active_positions_count = sum(1 for summary in position_summaries if summary.lifecycle_status == "active")
    hold_exit_policy_summary = PaperPortfolioHoldExitPolicySummary(
        applied=request.apply_exit_policy,
        policy_version="paper_exit_hold_policy_v1" if request.apply_exit_policy else "hold_only_v0",
        active_positions_count=active_positions_count,
        exited_positions_count=exited_positions_count,
        unsupported_exit_count=unsupported_exit_count,
        exit_reason_distribution=exit_reason_distribution,
        notes=policy_notes,
    )

    range_label = "all available local history"
    if request.date_from or request.date_to:
        range_label = f"{request.date_from or 'start'} to {request.date_to or 'latest'}"

    assumptions = PaperPortfolioAssumptions(
        entry_rule="Open each supported position at the first local daily close on or after the decision date.",
        allocation_rule="Allocate equal planned capital across all supported entries that are allowed to open under the current policy mode.",
        cash_ledger_rule="Initial capital stays in cash until each supported position's entry date, then allocated capital is deducted; if a supported exit occurs, exit value returns to cash on that exit valuation date.",
        mark_to_market_rule="At each NAV date, each active position is marked using its latest available local daily close on or before that date.",
        duplicate_entry_rule="If a later entry arrives while earlier exposure in the same entity is still active, the later duplicate is skipped; if the earlier exposure has a supported replacement exit before the later entry date, the later entry may open.",
        lifecycle_rule=("Positions open on their entry date and remain active until the end of the selected valuation window." if not request.apply_exit_policy else "Positions open on their entry date and remain active until the first supported replacement, deterioration, hard-conflict, or negative-signal exit; otherwise they hold to window end."),
        exit_policy_rule=("Exit policy disabled: positions hold to the selected window end." if not request.apply_exit_policy else "Exit policy v1 checks later same-entity replacement decisions, later non-usable monitoring states, later hard conflicts, and later warning/critical findings for the same entity; the earliest supported trigger wins, and exits use the first local daily close on or after that trigger date."),
        benchmark_rule="If local benchmark history exists, compare the generated paper NAV path against a simple broad-window benchmark return using the same start and end dates.",
    )

    return PaperPortfolioNavResponse(
        generated_at=_now_utc(),
        date_range=PaperPortfolioDateRange(start=request.date_from, end=request.date_to, label=range_label),
        cohort_definition=PaperPortfolioCohortDefinition(cohort_key=request.cohort_definition, label=shadow_service._COHORT_LABELS[request.cohort_definition]),
        assumptions=assumptions,
        initial_capital=_round(request.initial_capital) or request.initial_capital,
        ending_value=_round(ending_value) or 0.0,
        cash_remaining=_round(cash_remaining) or 0.0,
        active_positions_count=active_positions_count,
        exited_positions_count=exited_positions_count,
        unsupported_exit_count=unsupported_exit_count,
        exit_reason_distribution=exit_reason_distribution,
        active_positions=active_position_ids,
        closed_or_inactive_positions=closed_or_inactive_position_ids,
        hold_exit_policy_summary=hold_exit_policy_summary,
        nav_summary=nav_summary,
        nav_points=nav_points,
        position_summaries=position_summaries,
        benchmark_summary=benchmark_summary,
        comparison_summary=comparison_summary,
        warnings=warnings,
        missing_data_notes=missing_data_notes,
    )
