"""Integration tests for health endpoints.

These tests use a real FastAPI test client but mock the DB session to avoid
requiring a running PostgreSQL instance in CI.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.dependencies import get_session


@pytest.fixture
async def client():
    """HTTP client with DB dependency overridden."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 1))

    app.dependency_overrides[get_session] = lambda: mock_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_liveness(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness(client):
    response = await client.get("/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
