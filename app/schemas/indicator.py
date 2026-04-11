import uuid
from datetime import date

from pydantic import BaseModel


class IndicatorDataPoint(BaseModel):
    date: date
    value: float | None


class IndicatorResponse(BaseModel):
    instrument_id: uuid.UUID
    indicator_name: str
    params: dict
    data: list[IndicatorDataPoint]


class IndicatorInfo(BaseModel):
    name: str
    description: str
    params: dict


class IndicatorListResponse(BaseModel):
    indicators: list[IndicatorInfo]
