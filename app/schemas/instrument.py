import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class InstrumentCreate(BaseModel):
    ticker: str
    name: str | None = None
    asset_class: str | None = None
    currency: str = "USD"

    @field_validator("ticker")
    @classmethod
    def ticker_uppercase(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper().strip()


class InstrumentRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    ticker: str
    name: str | None
    asset_class: str | None
    currency: str
    created_at: datetime


class InstrumentList(BaseModel):
    items: list[InstrumentRead]
    total: int
