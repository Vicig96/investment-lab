from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
from app.core.dependencies import get_session
from app.main import app
from app.schemas.copilot_journal import DecisionCreateRequest


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
def scorecard_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


async def test_scorecard_endpoint_returns_local_summary(client, scorecard_paths):
    journal_service.save_decision(
        journal_service.create_decision(
            DecisionCreateRequest(
                user_query="Rank SPY",
                detected_intent="asset_ranking",
                top_deterministic_result="SPY",
                recommendation_status="eligible_new_position",
                recommended_action_type="open_new_position",
                action_taken="accepted",
            )
        )
    )

    response = await client.post("/api/v1/copilot/scorecard", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["journal_summary"]["total_journal_decisions"] == 1
    assert data["recommendation_summary"]["eligible_ideas_acted_on"] == 1
