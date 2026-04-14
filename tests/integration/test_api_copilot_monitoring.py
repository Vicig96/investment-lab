from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

from app.core.dependencies import get_session
from app.main import app
import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_personalization as personalization_service


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
def monitoring_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    base_dir = tmp_path / "monitoring_api"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    profile_path = base_dir / "profile.json"
    portfolio_path = base_dir / "portfolio.json"
    findings_path = base_dir / "findings.jsonl"
    snapshots_path = base_dir / "monitoring_snapshots.jsonl"
    journal_path = base_dir / "journal.jsonl"

    profile_path.write_text(
        json.dumps(
            {
                "profile_name": "API Profile",
                "investment_objective": "Compound capital",
                "time_horizon": "5y",
                "risk_tolerance": "moderate",
                "max_acceptable_drawdown": 0.25,
                "preferred_assets": ["SPY"],
                "disallowed_assets": [],
                "preferred_strategy_bias": "defensive",
                "liquidity_needs": "high",
                "notes": "API test",
            }
        ),
        encoding="utf-8",
    )
    portfolio_path.write_text(
        json.dumps(
            {
                "portfolio_name": "API Portfolio",
                "base_currency": "USD",
                "cash_available": 5000,
                "positions": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(personalization_service, "PORTFOLIO_PATH", portfolio_path)
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", findings_path)
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", snapshots_path)
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", journal_path)
    return findings_path, snapshots_path, knowledge_dir


async def test_run_monitoring_endpoint_and_list_findings(client, monitoring_paths, monkeypatch: pytest.MonkeyPatch):
    findings_path, snapshots_path, _ = monitoring_paths

    async def _fake_known_tickers(session):
        return {"SPY"}

    async def _fake_load(*args, **kwargs):
        return {"SPY": _df("2023-01-02", 260, 100.0, 0.20)}

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)
    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    response = await client.post("/api/v1/copilot/monitoring/run", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["current_snapshot"]["snapshot_id"]
    assert snapshots_path.exists()
    assert findings_path.exists()

    list_response = await client.get("/api/v1/copilot/monitoring/findings?severity=warning")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] >= 1
    assert all(entry["severity"] == "warning" for entry in listed["entries"])
