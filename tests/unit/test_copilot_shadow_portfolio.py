from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_shadow_portfolio as shadow_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_shadow_portfolio import ShadowPortfolioRequest, ShadowPortfolioResponse


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


@pytest.mark.asyncio
async def test_supported_paper_position_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Rank SPY",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {"SPY": _df("2026-04-10", 3, 100.0, 2.0)}

    monkeypatch.setattr(shadow_service, "load_ohlcv_multi", _fake_load)

    response = await shadow_service.build_shadow_portfolio(None, ShadowPortfolioRequest(cohort_definition="accepted", benchmark_ticker=None))

    assert response.paper_summary.total_positions == 1
    assert response.supported_positions == 1
    position = response.paper_positions[0]
    assert position.supported is True
    assert position.assumed_entry_price == 100.0
    assert position.latest_mark_price == 104.0
    assert position.simple_return_pct == 4.0


@pytest.mark.asyncio
async def test_unsupported_position_when_price_history_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Rank QQQ",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {}

    monkeypatch.setattr(shadow_service, "load_ohlcv_multi", _fake_load)

    response = await shadow_service.build_shadow_portfolio(None, ShadowPortfolioRequest(cohort_definition="accepted", benchmark_ticker=None))

    assert response.supported_positions == 0
    assert response.unsupported_positions == 1
    assert response.paper_positions[0].supported is False
    assert any("No local price history" in note for note in response.paper_positions[0].support_notes)


@pytest.mark.asyncio
async def test_equal_weight_paper_cohort_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        user_query="Paper GLD",
        timestamp="2026-04-10T10:00:00+00:00",
        top_result="GLD",
        final_entity="GLD",
        recommendation_status="eligible",
        action_taken="paper_only",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        ticker = tickers[0]
        if ticker == "SPY":
            return {"SPY": _df("2026-04-10", 2, 100.0, 10.0)}
        if ticker == "GLD":
            return {"GLD": _df("2026-04-10", 2, 200.0, -10.0)}
        return {}

    monkeypatch.setattr(shadow_service, "load_ohlcv_multi", _fake_load)

    response = await shadow_service.build_shadow_portfolio(None, ShadowPortfolioRequest(cohort_definition="accepted_plus_paper_only", benchmark_ticker=None))

    assert response.paper_summary.total_positions == 2
    assert response.paper_summary.supported_positions == 2
    assert response.paper_summary.average_simple_return_pct == 2.5
    assert response.paper_summary.median_simple_return_pct == 2.5
    assert response.paper_summary.equal_weight_simple_return_pct == 2.5
    assert response.paper_summary.positive_count == 1
    assert response.paper_summary.negative_count == 1


@pytest.mark.asyncio
async def test_optional_benchmark_comparison_when_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(
        user_query="Accept SPY",
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

    monkeypatch.setattr(shadow_service, "load_ohlcv_multi", _fake_load)

    response = await shadow_service.build_shadow_portfolio(None, ShadowPortfolioRequest(cohort_definition="accepted", benchmark_ticker="SPY"))

    assert response.benchmark_summary.supported is True
    assert response.benchmark_summary.simple_return_pct == 2.0
    assert response.comparison_summary.benchmark_comparison_supported is True
    assert response.comparison_summary.cohort_equal_weight_simple_return_pct == 5.0
    assert response.comparison_summary.benchmark_simple_return_pct == 2.0


@pytest.mark.asyncio
async def test_missing_data_behavior_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        return {}

    monkeypatch.setattr(shadow_service, "load_ohlcv_multi", _fake_load)

    response = await shadow_service.build_shadow_portfolio(None, ShadowPortfolioRequest(cohort_definition="accepted"))

    assert response.paper_summary.total_positions == 0
    assert any("No journal decisions matched" in warning for warning in response.warnings)
    assert any("No supported paper positions were available" in note for note in response.missing_data_notes)


@pytest.mark.asyncio
async def test_shadow_portfolio_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_build(session, request):
        return ShadowPortfolioResponse(
            generated_at="2026-04-14T12:00:00+00:00",
            date_range={"start": "2026-03-15", "end": "2026-04-14", "label": "2026-03-15 to 2026-04-14"},
            cohort_definition={"cohort_key": "accepted", "label": "Accepted decisions", "weighting": "equal_weight", "benchmark_ticker": "SPY"},
            paper_positions=[
                {
                    "decision_id": "decision-1",
                    "entity": "SPY",
                    "decision_timestamp": "2026-04-01T09:00:00+00:00",
                    "assumed_entry_timestamp": "2026-04-01T00:00:00+00:00",
                    "assumed_entry_price": 100.0,
                    "latest_mark_timestamp": "2026-04-14T00:00:00+00:00",
                    "latest_mark_price": 104.0,
                    "supported": True,
                    "support_notes": [],
                    "simple_return_pct": 4.0,
                }
            ],
            supported_positions=1,
            unsupported_positions=0,
            paper_summary={
                "total_positions": 1,
                "supported_positions": 1,
                "unsupported_positions": 0,
                "average_simple_return_pct": 4.0,
                "median_simple_return_pct": 4.0,
                "equal_weight_simple_return_pct": 4.0,
                "positive_count": 1,
                "negative_count": 0,
            },
            benchmark_summary={
                "benchmark_ticker": "SPY",
                "supported": True,
                "assumed_entry_timestamp": "2026-04-01T00:00:00+00:00",
                "assumed_entry_price": 100.0,
                "latest_mark_timestamp": "2026-04-14T00:00:00+00:00",
                "latest_mark_price": 102.0,
                "simple_return_pct": 2.0,
                "support_notes": [],
            },
            comparison_summary={
                "benchmark_comparison_supported": True,
                "benchmark_ticker": "SPY",
                "cohort_equal_weight_simple_return_pct": 4.0,
                "benchmark_simple_return_pct": 2.0,
                "interpretation": "The supported accepted decisions currently mark above SPY.",
                "notes": [],
            },
            warnings=["Shadow portfolio results are paper estimates only."],
            missing_data_notes=[],
        )

    monkeypatch.setattr(shadow_service, "build_shadow_portfolio", _fake_build)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="How would my accepted ideas have done in paper mode?"),
    )

    assert response.detected_intent == "shadow_portfolio"
    assert response.tools_used == ["run_shadow_portfolio"]
    assert response.answer.headline == "Shadow portfolio ready"
    assert response.supporting_data["shadow_portfolio"]["paper_summary"]["equal_weight_simple_return_pct"] == 4.0
