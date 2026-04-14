from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_paper_portfolio_nav as paper_nav_service
from app.core.dependencies import get_session
from app.main import app
from app.schemas.copilot_journal import DecisionCreateRequest
from app.schemas.copilot_paper_portfolio_nav import PaperPortfolioNavResponse


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
def pilot_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


def _paper_nav_response(*, cohort_key: str, total_return: float | None, exit_delta: float | None = None) -> PaperPortfolioNavResponse:
    return PaperPortfolioNavResponse(
        generated_at="2026-04-14T10:00:00+00:00",
        date_range={"start": "2026-04-01", "end": "2026-04-14", "label": "2026-04-01 to 2026-04-14"},
        cohort_definition={"cohort_key": cohort_key, "label": cohort_key},
        assumptions={
            "entry_rule": "entry",
            "allocation_rule": "allocation",
            "cash_ledger_rule": "cash",
            "mark_to_market_rule": "mark",
            "duplicate_entry_rule": "duplicate",
            "lifecycle_rule": "lifecycle",
            "exit_policy_rule": "exit",
            "benchmark_rule": "benchmark",
        },
        initial_capital=10000.0,
        ending_value=10000.0 * (1 + (total_return or 0.0) / 100.0),
        cash_remaining=0.0,
        active_positions_count=1,
        exited_positions_count=0 if exit_delta is None else 1,
        unsupported_exit_count=0,
        exit_reason_distribution=[],
        active_positions=[],
        closed_or_inactive_positions=[],
        hold_exit_policy_summary={
            "applied": exit_delta is not None,
            "policy_version": "paper_exit_hold_policy_v1" if exit_delta is not None else "hold_only_v0",
            "active_positions_count": 1,
            "exited_positions_count": 0 if exit_delta is None else 1,
            "unsupported_exit_count": 0,
            "exit_reason_distribution": [],
            "notes": [],
        },
        nav_summary={
            "total_positions_entered": 1,
            "supported_positions": 1,
            "unsupported_positions": 0,
            "total_portfolio_simple_return_pct": total_return,
            "max_paper_drawdown_pct": 0.0,
            "average_position_simple_return_pct": total_return,
            "median_position_simple_return_pct": total_return,
            "positive_positions_count": 1 if (total_return or 0) > 0 else 0,
            "negative_positions_count": 1 if (total_return or 0) < 0 else 0,
        },
        nav_points=[],
        position_summaries=[],
        benchmark_summary={
            "benchmark_ticker": "SPY",
            "supported": True,
            "assumed_entry_timestamp": None,
            "assumed_entry_price": None,
            "latest_mark_timestamp": None,
            "latest_mark_price": None,
            "simple_return_pct": 2.0,
            "ending_value": None,
            "support_notes": [],
        },
        comparison_summary={
            "benchmark_comparison_supported": True,
            "benchmark_ticker": "SPY",
            "portfolio_simple_return_pct": total_return,
            "benchmark_simple_return_pct": 2.0,
            "hold_to_window_end_ending_value": 10200.0 if exit_delta is not None else None,
            "exit_policy_ending_value_difference": exit_delta,
            "interpretation": "comparison",
            "notes": [],
        },
        warnings=[],
        missing_data_notes=[],
    )


async def test_forward_validation_pilot_endpoint_returns_local_summary(client, pilot_paths, monkeypatch: pytest.MonkeyPatch):
    journal_service.save_decision(
        journal_service.create_decision(
            DecisionCreateRequest(
                user_query="Accept SPY",
                detected_intent="asset_ranking",
                top_deterministic_result="SPY",
                recommendation_status="eligible_new_position",
                action_taken="accepted",
            )
        )
    )

    async def _fake_paper_nav(session, request):
        if request.cohort_definition == "accepted":
            return _paper_nav_response(cohort_key="accepted", total_return=4.0)
        if request.cohort_definition == "paper_only":
            return _paper_nav_response(cohort_key="paper_only", total_return=1.0)
        if request.apply_exit_policy:
            return _paper_nav_response(cohort_key=request.cohort_definition, total_return=3.0, exit_delta=100.0)
        return _paper_nav_response(cohort_key=request.cohort_definition, total_return=2.0)

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_paper_nav)

    response = await client.post("/api/v1/copilot/forward_validation_pilot", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["review_protocol"]["total_decisions_in_period"] == 1
    assert data["cohort_comparison_summary"]["accepted_vs_paper_only"]["supported"] is True
    assert data["cohort_comparison_summary"]["hold_only_vs_exit_policy"]["supported"] is True
