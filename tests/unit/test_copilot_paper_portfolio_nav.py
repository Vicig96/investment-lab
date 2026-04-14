from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_paper_portfolio_nav as paper_nav_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_monitoring import MonitoringAssetState, MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_paper_portfolio_nav import PaperPortfolioNavRequest, PaperPortfolioNavResponse


def _df(start: str, periods: int, base: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=periods)
    rows = []
    price = base
    for current_date in dates:
        rows.append(
            {
                "date": current_date.date(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1000,
            }
        )
        price += step
    frame = pd.DataFrame(rows)
    return frame.set_index("date")


def _seed_decision(
    *,
    user_query: str,
    timestamp: str,
    top_result: str | None = None,
    final_entity: str | None = None,
    recommendation_status: str | None = None,
    action_taken: str | None = None,
) -> None:
    record = journal_service.create_decision(
        DecisionCreateRequest(
            user_query=user_query,
            detected_intent="asset_ranking",
            top_deterministic_result=top_result,
            final_recommendation=(
                JournalRecommendationSnapshot(recommended_entity=final_entity)
                if final_entity is not None
                else None
            ),
            recommendation_status=recommendation_status,
            action_taken=action_taken,
        )
    )
    record.timestamp = timestamp
    journal_service.save_decision(record)


def _setup_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


def _append_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def _snapshot(*, timestamp: str, ticker: str, recommendation_status: str | None, hard_conflicts: list[str] | None = None) -> MonitoringSnapshotRecord:
    return MonitoringSnapshotRecord(
        snapshot_id=f"snapshot-{timestamp}",
        timestamp=timestamp,
        universe_tickers=[ticker],
        best_eligible_asset=(ticker if recommendation_status and recommendation_status.startswith("eligible") else "OTHER"),
        best_eligible_status=recommendation_status,
        monitored_assets=[
            MonitoringAssetState(
                ticker=ticker,
                rank=1,
                recommendation_status=recommendation_status,
                hard_conflicts=hard_conflicts or [],
            )
        ],
    )


def _finding(*, timestamp: str, ticker: str, finding_type: str = "holding_drawdown_breach", severity: str = "warning") -> MonitoringFinding:
    return MonitoringFinding(
        finding_id=f"finding-{timestamp}",
        timestamp=timestamp,
        finding_type=finding_type,
        severity=severity,
        entity=ticker,
        headline=f"{ticker} issue",
        summary="Local monitoring issue.",
        why_it_matters="Used in tests.",
        suggested_next_action="Review locally.",
        source_snapshot_ref="snapshot",
    )


@pytest.mark.asyncio
async def test_supported_paper_portfolio_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept SPY",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 3, 100.0, 2.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, initial_capital=1000.0),
    )

    assert response.initial_capital == 1000.0
    assert response.nav_summary.supported_positions == 1
    assert response.nav_summary.unsupported_positions == 0
    assert response.ending_value == 1040.0
    assert response.cash_remaining == 0.0
    assert response.nav_summary.total_portfolio_simple_return_pct == 4.0
    assert response.position_summaries[0].allocated_capital == 1000.0
    assert response.position_summaries[0].current_value == 1040.0


@pytest.mark.asyncio
async def test_unsupported_position_when_no_local_price_history_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept QQQ",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None),
    )

    assert response.nav_summary.supported_positions == 0
    assert response.nav_summary.unsupported_positions == 1
    assert response.position_summaries[0].supported is False
    assert response.position_summaries[0].lifecycle_status == "unsupported_missing_data"
    assert any("No local price history" in note for note in response.position_summaries[0].support_notes)


@pytest.mark.asyncio
async def test_simple_cash_allocation_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept SPY",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )
    _seed_decision(
        user_query="Accept GLD",
        timestamp="2026-04-14T09:00:00+00:00",
        top_result="GLD",
        final_entity="GLD",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        ticker = tickers[0]
        if ticker == "SPY":
            return {"SPY": _df("2026-04-10", 4, 100.0, 1.0)}
        if ticker == "GLD":
            return {"GLD": _df("2026-04-14", 2, 50.0, 2.0)}
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, initial_capital=1000.0),
    )

    assert response.position_summaries[0].allocated_capital == 500.0
    assert response.position_summaries[1].allocated_capital == 500.0
    assert response.nav_points[0].cash == 500.0
    assert response.nav_points[-1].cash == 0.0
    assert response.nav_points[-1].active_position_count == 2


@pytest.mark.asyncio
async def test_overlapping_duplicate_entries_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept SPY 1",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )
    _seed_decision(
        user_query="Accept SPY 2",
        timestamp="2026-04-11T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_add_to_existing",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 3, 100.0, 1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None),
    )

    assert response.nav_summary.supported_positions == 1
    assert response.nav_summary.unsupported_positions == 1
    inactive = [item for item in response.position_summaries if not item.supported][0]
    assert inactive.lifecycle_status == "inactive_duplicate"
    assert any("Duplicate concurrent entry was skipped" in note for note in inactive.support_notes)


@pytest.mark.asyncio
async def test_nav_points_are_generated_in_date_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept QQQ",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"QQQ": _df("2026-04-10", 3, 100.0, 3.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None),
    )

    assert [point.date for point in response.nav_points] == sorted(point.date for point in response.nav_points)
    assert response.nav_points[-1].portfolio_value > response.nav_points[0].portfolio_value
    assert response.nav_summary.max_paper_drawdown_pct == 0.0


@pytest.mark.asyncio
async def test_optional_benchmark_comparison_when_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept QQQ",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        ticker = tickers[0]
        if ticker == "QQQ":
            return {"QQQ": _df("2026-04-10", 2, 100.0, 5.0)}
        if ticker == "SPY":
            return {"SPY": _df("2026-04-10", 2, 100.0, 2.0)}
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker="SPY"),
    )

    assert response.benchmark_summary.supported is True
    assert response.benchmark_summary.simple_return_pct == 2.0
    assert response.comparison_summary.benchmark_comparison_supported is True
    assert response.comparison_summary.portfolio_simple_return_pct == 5.0
    assert response.comparison_summary.benchmark_simple_return_pct == 2.0


@pytest.mark.asyncio
async def test_hold_to_window_end_behavior_with_exit_policy_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept SPY",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 3, 100.0, 2.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True),
    )

    assert response.position_summaries[0].exit_policy_status == "hold_to_window_end"
    assert response.position_summaries[0].lifecycle_status == "active"
    assert response.exited_positions_count == 0


@pytest.mark.asyncio
async def test_exited_on_replacement_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept SPY first", timestamp="2026-04-10T09:00:00+00:00", top_result="SPY", final_entity="SPY", recommendation_status="eligible_new_position", action_taken="accepted")
    _seed_decision(user_query="Accept SPY replace", timestamp="2026-04-14T09:00:00+00:00", top_result="SPY", final_entity="SPY", recommendation_status="eligible_new_position", action_taken="accepted")

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 5, 100.0, 1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True, initial_capital=1000.0))

    replaced = next(item for item in response.position_summaries if item.exit_policy_status == "exited_on_replacement")
    assert replaced.assumed_exit_timestamp is not None
    assert response.exited_positions_count >= 1


@pytest.mark.asyncio
async def test_exited_on_deterioration_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept QQQ", timestamp="2026-04-10T09:00:00+00:00", top_result="QQQ", final_entity="QQQ", recommendation_status="eligible_new_position", action_taken="accepted")
    _append_jsonl(monitoring_service.SNAPSHOTS_PATH, [_snapshot(timestamp="2026-04-14T12:00:00+00:00", ticker="QQQ", recommendation_status="unsupported_by_knowledge")])

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"QQQ": _df("2026-04-10", 5, 100.0, 1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True))

    assert response.position_summaries[0].exit_policy_status == "exited_on_deterioration"
    assert response.position_summaries[0].supported_exit is True


@pytest.mark.asyncio
async def test_exited_on_hard_conflict_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept GLD", timestamp="2026-04-10T09:00:00+00:00", top_result="GLD", final_entity="GLD", recommendation_status="eligible_new_position", action_taken="accepted")
    _append_jsonl(monitoring_service.SNAPSHOTS_PATH, [_snapshot(timestamp="2026-04-14T12:00:00+00:00", ticker="GLD", recommendation_status="rejected_by_profile", hard_conflicts=["Profile conflict"])])

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"GLD": _df("2026-04-10", 5, 100.0, -1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True))

    assert response.position_summaries[0].exit_policy_status == "exited_on_hard_conflict"
    assert response.position_summaries[0].lifecycle_status == "exited"


@pytest.mark.asyncio
async def test_exited_on_negative_signal_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept IWM", timestamp="2026-04-10T09:00:00+00:00", top_result="IWM", final_entity="IWM", recommendation_status="eligible_new_position", action_taken="accepted")
    _append_jsonl(monitoring_service.FINDINGS_PATH, [_finding(timestamp="2026-04-14T12:00:00+00:00", ticker="IWM")])

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"IWM": _df("2026-04-10", 5, 100.0, -1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True))

    assert response.position_summaries[0].exit_policy_status == "exited_on_negative_signal"


@pytest.mark.asyncio
async def test_unsupported_exit_decision_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept TLT", timestamp="2026-04-10T09:00:00+00:00", top_result="TLT", final_entity="TLT", recommendation_status="eligible_new_position", action_taken="accepted")
    _append_jsonl(monitoring_service.FINDINGS_PATH, [_finding(timestamp="2026-04-20T12:00:00+00:00", ticker="TLT")])

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"TLT": _df("2026-04-10", 3, 100.0, 1.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True))

    assert response.position_summaries[0].exit_policy_status == "unsupported_exit_decision"
    assert response.position_summaries[0].supported_exit is False
    assert response.position_summaries[0].lifecycle_status == "active"


@pytest.mark.asyncio
async def test_cash_ledger_returns_after_exit_and_nav_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept SPY", timestamp="2026-04-10T09:00:00+00:00", top_result="SPY", final_entity="SPY", recommendation_status="eligible_new_position", action_taken="accepted")
    _append_jsonl(monitoring_service.FINDINGS_PATH, [_finding(timestamp="2026-04-14T12:00:00+00:00", ticker="SPY")])

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 5, 100.0, 5.0)}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)
    hold_response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=False, initial_capital=1000.0))
    exit_response = await paper_nav_service.build_paper_portfolio_nav(None, PaperPortfolioNavRequest(cohort_definition="accepted", benchmark_ticker=None, apply_exit_policy=True, initial_capital=1000.0))

    assert exit_response.cash_remaining == 1100.0
    assert exit_response.nav_points[-1].cash == 1100.0
    assert exit_response.ending_value != hold_response.ending_value
    assert exit_response.comparison_summary.exit_policy_ending_value_difference == -100.0


@pytest.mark.asyncio
async def test_missing_data_behavior_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await paper_nav_service.build_paper_portfolio_nav(
        None,
        PaperPortfolioNavRequest(cohort_definition="accepted"),
    )

    assert response.nav_summary.total_positions_entered == 0
    assert response.nav_summary.total_portfolio_simple_return_pct is None
    assert any("No journal decisions matched" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_paper_portfolio_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_build(session, request):
        return PaperPortfolioNavResponse(
            generated_at="2026-04-14T12:00:00+00:00",
            date_range={"start": "2026-03-15", "end": "2026-04-14", "label": "2026-03-15 to 2026-04-14"},
            cohort_definition={"cohort_key": "accepted", "label": "Accepted decisions"},
            assumptions={
                "entry_rule": "Open on first local close on or after the decision date.",
                "allocation_rule": "Equal weight supported entries.",
                "cash_ledger_rule": "Cash is deducted when positions open.",
                "mark_to_market_rule": "Mark using latest local close on or before each NAV date.",
                "duplicate_entry_rule": "Skip duplicate active entities.",
                "lifecycle_rule": "Positions remain active until the end of the selected window.",
                "exit_policy_rule": "Exit policy disabled.",
                "benchmark_rule": "Compare with SPY when local benchmark data exists.",
            },
            initial_capital=10000.0,
            ending_value=10400.0,
            cash_remaining=0.0,
            active_positions_count=1,
            exited_positions_count=0,
            unsupported_exit_count=0,
            exit_reason_distribution=[{"item": "hold_to_window_end", "count": 1}],
            active_positions=["decision-1"],
            closed_or_inactive_positions=[],
            hold_exit_policy_summary={
                "applied": False,
                "policy_version": "hold_only_v0",
                "active_positions_count": 1,
                "exited_positions_count": 0,
                "unsupported_exit_count": 0,
                "exit_reason_distribution": [{"item": "hold_to_window_end", "count": 1}],
                "notes": [],
            },
            nav_summary={
                "total_positions_entered": 1,
                "supported_positions": 1,
                "unsupported_positions": 0,
                "total_portfolio_simple_return_pct": 4.0,
                "max_paper_drawdown_pct": 0.0,
                "average_position_simple_return_pct": 4.0,
                "median_position_simple_return_pct": 4.0,
                "positive_positions_count": 1,
                "negative_positions_count": 0,
            },
            nav_points=[
                {
                    "date": "2026-04-01",
                    "portfolio_value": 10000.0,
                    "cash": 0.0,
                    "invested_value": 10000.0,
                    "active_position_count": 1,
                },
                {
                    "date": "2026-04-14",
                    "portfolio_value": 10400.0,
                    "cash": 0.0,
                    "invested_value": 10400.0,
                    "active_position_count": 1,
                },
            ],
            position_summaries=[
                {
                    "decision_id": "decision-1",
                    "entity": "SPY",
                    "assumed_entry_timestamp": "2026-04-01T00:00:00+00:00",
                    "assumed_entry_price": 100.0,
                    "exit_policy_status": "hold_to_window_end",
                    "exit_trigger_type": None,
                    "exit_trigger_timestamp": None,
                    "assumed_exit_timestamp": None,
                    "assumed_exit_price": None,
                    "realized_or_closed_simple_return_pct": None,
                    "current_mark_timestamp": "2026-04-14T00:00:00+00:00",
                    "current_mark_price": 104.0,
                    "allocated_capital": 10000.0,
                    "current_value": 10400.0,
                    "simple_return_pct": 4.0,
                    "supported": True,
                    "supported_exit": None,
                    "support_notes": [],
                    "lifecycle_notes": [],
                    "lifecycle_status": "active",
                }
            ],
            benchmark_summary={
                "benchmark_ticker": "SPY",
                "supported": True,
                "assumed_entry_timestamp": "2026-04-01T00:00:00+00:00",
                "assumed_entry_price": 100.0,
                "latest_mark_timestamp": "2026-04-14T00:00:00+00:00",
                "latest_mark_price": 102.0,
                "simple_return_pct": 2.0,
                "ending_value": 10200.0,
                "support_notes": [],
            },
            comparison_summary={
                "benchmark_comparison_supported": True,
                "benchmark_ticker": "SPY",
                "portfolio_simple_return_pct": 4.0,
                "benchmark_simple_return_pct": 2.0,
                "hold_to_window_end_ending_value": 10400.0,
                "exit_policy_ending_value_difference": None,
                "interpretation": "The paper portfolio currently sits above SPY on a simple local NAV basis over the same broad window.",
                "notes": [],
            },
            warnings=["Paper portfolio NAV is a cautious local estimate only."],
            missing_data_notes=[],
        )

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_build)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="What would my paper portfolio NAV look like over this period?"),
    )

    assert response.detected_intent == "paper_portfolio_nav"
    assert response.tools_used == ["run_paper_portfolio_nav"]
    assert response.answer.headline == "Paper portfolio NAV ready"
    assert response.supporting_data["paper_portfolio_nav"]["nav_summary"]["total_portfolio_simple_return_pct"] == 4.0
