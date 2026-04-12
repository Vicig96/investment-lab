from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ScreenerRequest(BaseModel):
    instrument_tickers: list[str]
    date_from: date | None = None
    date_to: date | None = None
    top_n: int = Field(default=5, ge=1, le=50)


class RankedAsset(BaseModel):
    ticker: str
    score: float
    label: str  # "BUY" | "WATCH" | "AVOID"
    history_bars: int
    data_quality: str  # "GOOD" | "LIMITED" | "INSUFFICIENT"
    insufficient_history_reason: str | None
    ret_20d: float | None
    ret_60d: float | None
    ret_120d: float | None
    dist_sma_50: float | None
    dist_sma_200: float | None
    vol_20d: float | None
    drawdown_60d: float | None  # positive absolute value of max drawdown in window
    suggested_weight: float | None


class ScreenerResponse(BaseModel):
    snapshot_date: date
    universe_size: int
    ranked_assets: list[RankedAsset]
