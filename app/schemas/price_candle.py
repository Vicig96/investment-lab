import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class PriceCandleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    instrument_id: uuid.UUID
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal | None
    volume: int | None


class CandleList(BaseModel):
    items: list[PriceCandleRead]
    total: int


class PriceSummary(BaseModel):
    instrument_id: uuid.UUID
    ticker: str
    total_candles: int
    date_from: date | None
    date_to: date | None
    last_close: Decimal | None
