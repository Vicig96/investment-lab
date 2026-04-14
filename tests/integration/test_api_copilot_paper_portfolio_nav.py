from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_paper_portfolio_nav as paper_nav_service
from app.core.dependencies import get_session
from app.main import app
from app.schemas.copilot_journal import DecisionCreateRequest


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


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    app.dependency_overrides[get_session] = lambda: mock_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def paper_nav_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


async def test_paper_portfolio_nav_endpoint_returns_local_summary(client, paper_nav_paths, monkeypatch: pytest.MonkeyPatch):
    decision = journal_service.create_decision(
        DecisionCreateRequest(
            user_query="Accept SPY",
            detected_intent="asset_ranking",
            top_deterministic_result="SPY",
            recommendation_status="eligible_new_position",
            action_taken="accepted",
        )
    )
    decision.timestamp = "2026-04-10T09:00:00+00:00"
    journal_service.save_decision(decision)

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        if tickers[0] == "SPY":
            return {"SPY": _df("2026-04-10", 2, 100.0, 2.0)}
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await client.post("/api/v1/copilot/paper_portfolio_nav", json={"cohort_definition": "accepted", "benchmark_ticker": None})

    assert response.status_code == 200
    data = response.json()
    assert data["nav_summary"]["supported_positions"] == 1
    assert data["ending_value"] == 10200.0
    assert data["position_summaries"][0]["entity"] == "SPY"


async def test_paper_portfolio_nav_endpoint_supports_exit_policy(client, paper_nav_paths, monkeypatch: pytest.MonkeyPatch):
    decision = journal_service.create_decision(
        DecisionCreateRequest(
            user_query="Accept SPY",
            detected_intent="asset_ranking",
            top_deterministic_result="SPY",
            recommendation_status="eligible_new_position",
            action_taken="accepted",
        )
    )
    decision.timestamp = "2026-04-10T09:00:00+00:00"
    journal_service.save_decision(decision)
    monitoring_service.FINDINGS_PATH.write_text(
        '{"finding_id":"f1","timestamp":"2026-04-14T12:00:00+00:00","finding_type":"holding_drawdown_breach","severity":"warning","entity":"SPY","headline":"SPY issue","summary":"issue","why_it_matters":"issue","suggested_next_action":"review","source_snapshot_ref":"s1"}\n',
        encoding="utf-8",
    )

    async def _fake_load(session, tickers, from_date=None, to_date=None):
        if tickers[0] == "SPY":
            return {"SPY": _df("2026-04-10", 5, 100.0, 5.0)}
        return {}

    monkeypatch.setattr(paper_nav_service, "load_ohlcv_multi", _fake_load)

    response = await client.post("/api/v1/copilot/paper_portfolio_nav", json={"cohort_definition": "accepted", "benchmark_ticker": None, "apply_exit_policy": True, "initial_capital": 1000.0})

    assert response.status_code == 200
    data = response.json()
    assert data["exited_positions_count"] == 1
    assert data["position_summaries"][0]["exit_policy_status"] == "exited_on_negative_signal"
    assert data["cash_remaining"] == 1100.0
