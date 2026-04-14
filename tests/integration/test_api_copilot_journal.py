"""Integration tests for the copilot journal API endpoints.

Uses httpx + ASGITransport against the real FastAPI app.
Monkeypatches JOURNAL_PATH so the real data/copilot/journal.jsonl is never touched.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["DEBUG"] = "false"

from app.core.dependencies import get_session
from app.main import app
import app.services.copilot_journal as journal_service


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
def temp_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JOURNAL_PATH to a temporary file for each test."""
    jp = tmp_path / "journal.jsonl"
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", jp)
    return jp


# ── POST /copilot/journal ──────────────────────────────────────────────────────

async def test_save_decision_returns_201(client, temp_journal):
    body = {
        "user_query": "Rank SPY, QQQ, TLT",
        "detected_intent": "asset_ranking",
        "top_deterministic_result": "SPY",
        "recommendation_status": "eligible",
        "recommended_action_type": "open_new_position",
    }
    response = await client.post("/api/v1/copilot/journal", json=body)
    assert response.status_code == 201
    data = response.json()
    assert "decision_id" in data
    assert data["user_query"] == "Rank SPY, QQQ, TLT"
    assert data["top_deterministic_result"] == "SPY"
    assert data["timestamp"] is not None


async def test_save_decision_creates_file(client, temp_journal):
    assert not temp_journal.exists()
    body = {"user_query": "Test", "detected_intent": "asset_ranking"}
    response = await client.post("/api/v1/copilot/journal", json=body)
    assert response.status_code == 201
    assert temp_journal.exists()


async def test_save_decision_with_initial_action(client, temp_journal):
    body = {
        "user_query": "Should I buy GLD?",
        "detected_intent": "recommendation_explanation",
        "top_deterministic_result": "GLD",
        "action_taken": "watchlist",
    }
    response = await client.post("/api/v1/copilot/journal", json=body)
    assert response.status_code == 201
    data = response.json()
    assert data["action_taken"] == "watchlist"
    assert data["action_taken_timestamp"] is not None


# ── PATCH /copilot/journal/{decision_id} ──────────────────────────────────────

async def test_update_action_taken(client, temp_journal):
    # First save a record.
    save_resp = await client.post(
        "/api/v1/copilot/journal",
        json={"user_query": "Rank assets", "detected_intent": "asset_ranking"},
    )
    assert save_resp.status_code == 201
    decision_id = save_resp.json()["decision_id"]

    # Now update with action taken.
    patch_resp = await client.patch(
        f"/api/v1/copilot/journal/{decision_id}",
        json={"action_taken": "accepted"},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["action_taken"] == "accepted"
    assert data["action_taken_timestamp"] is not None


async def test_update_outcome_notes(client, temp_journal):
    save_resp = await client.post(
        "/api/v1/copilot/journal",
        json={"user_query": "Strategy eval", "detected_intent": "strategy_evaluation"},
    )
    decision_id = save_resp.json()["decision_id"]

    patch_resp = await client.patch(
        f"/api/v1/copilot/journal/{decision_id}",
        json={"review_date": "2024-12-01", "outcome_notes": "Performed as expected."},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["review_date"] == "2024-12-01"
    assert data["outcome_notes"] == "Performed as expected."


async def test_update_nonexistent_returns_404(client, temp_journal):
    # Save one entry so the file exists.
    await client.post(
        "/api/v1/copilot/journal",
        json={"user_query": "Seed", "detected_intent": "unclear"},
    )
    response = await client.patch(
        "/api/v1/copilot/journal/nonexistent-uuid-999",
        json={"action_taken": "rejected"},
    )
    assert response.status_code == 404


# ── GET /copilot/journal ───────────────────────────────────────────────────────

async def test_list_returns_entries(client, temp_journal):
    for i in range(3):
        await client.post(
            "/api/v1/copilot/journal",
            json={"user_query": f"Query {i}", "detected_intent": "asset_ranking"},
        )

    response = await client.get("/api/v1/copilot/journal")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["entries"]) == 3


async def test_list_empty_when_no_file(client, temp_journal):
    # temp_journal path does not exist yet.
    response = await client.get("/api/v1/copilot/journal")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["entries"] == []


async def test_list_filter_ticker(client, temp_journal):
    for ticker in ["SPY", "QQQ", "SPY"]:
        await client.post(
            "/api/v1/copilot/journal",
            json={
                "user_query": f"Rank {ticker}",
                "detected_intent": "asset_ranking",
                "top_deterministic_result": ticker,
            },
        )

    response = await client.get("/api/v1/copilot/journal?ticker=SPY")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(e["top_deterministic_result"] == "SPY" for e in data["entries"])


async def test_list_filter_recommendation_status(client, temp_journal):
    for status in ["eligible", "rejected_by_profile", "eligible"]:
        await client.post(
            "/api/v1/copilot/journal",
            json={
                "user_query": "Test",
                "detected_intent": "asset_ranking",
                "recommendation_status": status,
            },
        )

    response = await client.get("/api/v1/copilot/journal?recommendation_status=eligible")
    data = response.json()
    assert data["total"] == 2


async def test_list_filter_action_taken(client, temp_journal):
    # Save 3 entries.
    ids = []
    for i in range(3):
        r = await client.post(
            "/api/v1/copilot/journal",
            json={"user_query": f"Q{i}", "detected_intent": "asset_ranking"},
        )
        ids.append(r.json()["decision_id"])

    # Accept the first two.
    for did in ids[:2]:
        await client.patch(f"/api/v1/copilot/journal/{did}", json={"action_taken": "accepted"})

    response = await client.get("/api/v1/copilot/journal?action_taken=accepted")
    data = response.json()
    assert data["total"] == 2


async def test_list_newest_first(client, temp_journal):
    for i in range(3):
        await client.post(
            "/api/v1/copilot/journal",
            json={"user_query": f"Q{i}", "detected_intent": "asset_ranking"},
        )

    response = await client.get("/api/v1/copilot/journal")
    entries = response.json()["entries"]
    # Verify descending timestamp order.
    for i in range(len(entries) - 1):
        assert entries[i]["timestamp"] >= entries[i + 1]["timestamp"]


async def test_list_limit(client, temp_journal):
    for i in range(8):
        await client.post(
            "/api/v1/copilot/journal",
            json={"user_query": f"Q{i}", "detected_intent": "asset_ranking"},
        )

    response = await client.get("/api/v1/copilot/journal?limit=3")
    data = response.json()
    assert len(data["entries"]) == 3
    assert data["total"] == 8


async def test_list_filter_date_range(client, temp_journal):
    await client.post(
        "/api/v1/copilot/journal",
        json={"user_query": "Q0", "detected_intent": "asset_ranking"},
    )

    response = await client.get("/api/v1/copilot/journal?date_from=2000-01-01&date_to=2099-12-31")
    data = response.json()
    assert response.status_code == 200
    assert data["total"] == 1
    assert len(data["entries"]) == 1


# ── GET /copilot/journal/{decision_id} ────────────────────────────────────────

async def test_get_single_decision(client, temp_journal):
    save_resp = await client.post(
        "/api/v1/copilot/journal",
        json={
            "user_query": "What should I do with TLT?",
            "detected_intent": "recommendation_explanation",
            "top_deterministic_result": "TLT",
        },
    )
    decision_id = save_resp.json()["decision_id"]

    get_resp = await client.get(f"/api/v1/copilot/journal/{decision_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["decision_id"] == decision_id
    assert data["top_deterministic_result"] == "TLT"


async def test_get_nonexistent_returns_404(client, temp_journal):
    response = await client.get("/api/v1/copilot/journal/nonexistent-uuid-abc")
    assert response.status_code == 404
