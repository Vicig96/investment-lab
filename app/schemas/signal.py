import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class SignalRunRequest(BaseModel):
    instrument_ids: list[uuid.UUID]
    strategy_name: str
    params: dict = {}
    date_from: date | None = None
    date_to: date | None = None
    persist: bool = False


class SignalRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    instrument_id: uuid.UUID
    date: date
    strategy_name: str
    params: dict
    direction: int
    strength: float | None
    created_at: datetime


class SignalList(BaseModel):
    items: list[SignalRead]
    total: int


class StrategyInfo(BaseModel):
    name: str
    description: str
    params: dict


class StrategyListResponse(BaseModel):
    strategies: list[StrategyInfo]
