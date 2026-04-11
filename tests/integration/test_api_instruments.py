"""Integration tests for instruments endpoint."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.dependencies import get_session
from app.models.instrument import Instrument


def _make_instrument(**kwargs) -> Instrument:
    from datetime import datetime, timezone
    defaults = dict(
        id=uuid.uuid4(),
        ticker="AAPL",
        name="Apple Inc.",
        asset_class="equity",
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    inst = MagicMock(spec=Instrument)
    for k, v in defaults.items():
        setattr(inst, k, v)
    return inst


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
async def client(mock_session):
    app.dependency_overrides[get_session] = lambda: mock_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_list_instruments_empty(client, mock_session):
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one=lambda: 0),
            MagicMock(scalars=lambda: MagicMock(all=lambda: [])),
        ]
    )
    response = await client.get("/api/v1/instruments")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


async def test_create_instrument(client, mock_session):
    inst = _make_instrument(ticker="MSFT", name="Microsoft")
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: None)
    )
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        import app.api.v1.instruments as inst_router
        original_validate = inst_router.InstrumentRead.model_validate

        def fake_validate(obj):
            from app.schemas.instrument import InstrumentRead
            import datetime
            return InstrumentRead(
                id=inst.id,
                ticker=inst.ticker,
                name=inst.name,
                asset_class=inst.asset_class,
                currency=inst.currency,
                created_at=inst.created_at,
            )
        mp.setattr(inst_router.InstrumentRead, "model_validate", staticmethod(fake_validate))

        response = await client.post(
            "/api/v1/instruments",
            json={"ticker": "msft", "name": "Microsoft", "currency": "USD"},
        )

    assert response.status_code == 201
    assert response.json()["ticker"] == "MSFT"


async def test_create_duplicate_returns_409(client, mock_session):
    existing = _make_instrument(ticker="AAPL")
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: existing)
    )
    response = await client.post(
        "/api/v1/instruments",
        json={"ticker": "AAPL", "currency": "USD"},
    )
    assert response.status_code == 409
