"""Schemas for the screener-rotation backtest endpoint."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.backtest import BacktestMetrics, EquityPoint, TradeRecord


class ScreenerRotationRequest(BaseModel):
    instrument_tickers: list[str]
    date_from: date
    date_to: date
    top_n: int = Field(default=5, ge=1, le=20)
    initial_capital: float = Field(default=10_000.0, gt=0)
    commission_bps: float = Field(default=10.0, ge=0)
    rebalance_frequency: str = Field(default="monthly")
    warmup_bars: int = Field(default=252, ge=0, le=1000)


class RebalanceEntry(BaseModel):
    date: str
    eligible_count: int
    cash_only: bool
    selected_tickers: list[str]
    weights: dict[str, float]


class HoldingSnapshot(BaseModel):
    date: str
    holdings: dict[str, float]


class BenchmarkComparison(BaseModel):
    ticker: str
    final_equity: float | None
    cagr: float | None
    max_drawdown: float | None
    sharpe_ratio: float | None
    equity_curve: list[EquityPoint]


class ScreenerRotationResult(BaseModel):
    date_from: str
    date_to: str
    universe: list[str]
    top_n: int
    rebalance_frequency: str
    warmup_bars_requested: int
    warmup_bars_available: int
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    rebalance_log: list[RebalanceEntry]
    holdings_by_rebalance: list[HoldingSnapshot]
    trades: list[TradeRecord]
    benchmark: BenchmarkComparison
