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
from app.schemas.copilot_monitoring import MonitoringAssetState, MonitoringSnapshotRecord


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
def comparative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


async def test_comparative_validation_endpoint_returns_local_summary(client, comparative_paths):
    accepted = journal_service.create_decision(
        DecisionCreateRequest(
            user_query="Rank SPY",
            detected_intent="asset_ranking",
            top_deterministic_result="SPY",
            recommendation_status="eligible_new_position",
            action_taken="accepted",
        )
    )
    accepted.timestamp = "2026-04-10T09:00:00+00:00"
    journal_service.save_decision(accepted)

    rejected = journal_service.create_decision(
        DecisionCreateRequest(
            user_query="Rank QQQ",
            detected_intent="asset_ranking",
            top_deterministic_result="QQQ",
            recommendation_status="rejected_by_profile",
            action_taken="rejected",
        )
    )
    rejected.timestamp = "2026-04-10T10:00:00+00:00"
    journal_service.save_decision(rejected)

    monitoring_service._append_jsonl(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-11T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    )
                ],
            )
        ],
    )

    response = await client.post("/api/v1/copilot/comparative_validation", json={})

    assert response.status_code == 200
    data = response.json()
    assert len(data["comparison_groups"]) == 6
    accepted_summary = next(item for item in data["cohort_summaries"] if item["cohort_key"] == "accepted")
    assert accepted_summary["total_decisions"] == 1
