import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class PositionRead(BaseModel):
    ticker: str
    shares: float
    weight: float
    value: float
    entry_price: float | None = None


class PortfolioSnapshotRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    snapshot_date: date
    nav: Decimal
    cash: Decimal
    positions: list[PositionRead]
    created_at: datetime


class PortfolioSnapshotList(BaseModel):
    items: list[PortfolioSnapshotRead]
    total: int


class RebalanceOrder(BaseModel):
    ticker: str
    action: str  # "buy" | "sell" | "hold"
    current_weight: float
    target_weight: float
    delta_weight: float
    estimated_shares: float | None = None
    estimated_value: float | None = None


class RebalanceResponse(BaseModel):
    snapshot_date: date
    nav: float
    orders: list[RebalanceOrder]
    note: str = ""


class PortfolioSimRequest(BaseModel):
    instrument_tickers: list[str]
    strategy_name: str
    params: dict = {}
    date_from: date
    date_to: date
    initial_capital: Decimal = Decimal("100000")
    target_weights: dict[str, float] | None = None
