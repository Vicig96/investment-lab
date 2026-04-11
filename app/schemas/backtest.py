import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    strategy_name: str
    instrument_tickers: list[str]
    params: dict = {}
    date_from: date
    date_to: date
    initial_capital: Decimal = Field(default=Decimal("100000"), gt=0)
    commission_bps: Decimal = Field(default=Decimal("10"), ge=0)


class BacktestRunRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    strategy_name: str
    instruments: list
    params: dict
    date_from: date
    date_to: date
    initial_capital: Decimal
    commission_bps: Decimal
    status: str
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None


class EquityPoint(BaseModel):
    date: str
    equity: float


class TradeRecord(BaseModel):
    date: str
    ticker: str
    action: str
    shares: float
    price: float
    commission: float
    pnl: float | None = None


class BacktestMetrics(BaseModel):
    cagr: float | None
    max_drawdown: float | None
    sharpe_ratio: float | None
    calmar_ratio: float | None
    win_rate: float | None
    total_trades: int | None
    final_equity: float | None


class BacktestResultRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    run_id: uuid.UUID
    cagr: Decimal | None
    max_drawdown: Decimal | None
    sharpe_ratio: Decimal | None
    calmar_ratio: Decimal | None
    win_rate: Decimal | None
    total_trades: int | None
    final_equity: Decimal | None
    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]


class BacktestList(BaseModel):
    items: list[BacktestRunRead]
    total: int
