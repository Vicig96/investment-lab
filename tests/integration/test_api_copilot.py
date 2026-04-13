import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

from app.core.dependencies import get_session
from app.main import app
import app.services.copilot as copilot_service
import app.services.copilot_personalization as personalization_service


def _local_temp_dir(name: str) -> Path:
    path = Path("tests") / ".tmp" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


async def test_list_copilot_tools(client):
    response = await client.get("/api/v1/copilot/tools")
    assert response.status_code == 200
    data = response.json()
    assert any(tool["name"] == "get_market_snapshot" for tool in data["tools"])
    assert any(tool["name"] == "run_strategy_evaluation" for tool in data["tools"])


async def test_get_market_snapshot_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    async def _fake_load(*args, **kwargs):
        return {
            "SPY": _df("2023-01-02", 260, 100.0, 0.2),
            "QQQ": _df("2023-01-02", 260, 90.0, 0.1),
        }

    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    response = await client.post(
        "/api/v1/copilot/get_market_snapshot",
        json={"instrument_tickers": ["SPY", "QQQ"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tool_name"] == "get_market_snapshot"
    assert len(data["assets"]) == 2
    assert data["assets"][0]["latest_price"] is not None


async def test_chat_endpoint_routes_to_ranking(client, monkeypatch: pytest.MonkeyPatch):
    async def _fake_load(*args, **kwargs):
        return {
            "SPY": _df("2023-01-02", 260, 100.0, 0.2),
            "QQQ": _df("2023-01-02", 260, 90.0, 0.1),
            "TLT": _df("2023-01-02", 260, 110.0, -0.02),
        }

    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)
    async def _fake_known_tickers(session):
        return {"SPY", "QQQ", "TLT", "GLD", "IWM"}

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)

    response = await client.post(
        "/api/v1/copilot/chat",
        json={"user_query": "Rank SPY, QQQ, TLT"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["detected_intent"] == "asset_ranking"
    assert "rank_assets" in data["tools_used"]
    assert "ranking" in data["supporting_data"]


async def test_query_knowledge_base_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    base_dir = _local_temp_dir("copilot_api_kb")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Integration Profile\","
            "\"investment_objective\":\"Compound capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"moderate\","
            "\"max_acceptable_drawdown\":0.25,"
            "\"preferred_assets\":[\"SPY\"],"
            "\"disallowed_assets\":[\"TQQQ\"],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Test\""
            "}"
        ),
        encoding="utf-8",
    )
    (knowledge_dir / "rules.md").write_text(
        "# Rules\nAvoid leveraged ETFs like TQQQ for the core portfolio.",
        encoding="utf-8",
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    response = await client.post(
        "/api/v1/copilot/query_knowledge_base",
        json={"query": "What do my rules say about TQQQ?", "top_k": 3},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "local_filesystem"
    assert data["matches"]
