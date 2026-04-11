"""In-memory portfolio state used during backtesting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Position:
    ticker: str
    shares: float
    entry_price: float
    entry_date: date


@dataclass
class PortfolioState:
    initial_capital: float
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    equity_curve: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = self.initial_capital

    def nav(self, prices: dict[str, float]) -> float:
        """Net asset value: cash + market value of all positions."""
        holdings_value = sum(
            pos.shares * prices.get(pos.ticker, pos.entry_price)
            for pos in self.positions.values()
        )
        return self.cash + holdings_value

    def record_equity(self, dt: date, prices: dict[str, float]) -> None:
        self.equity_curve.append({"date": dt.isoformat(), "equity": self.nav(prices)})

    def open_position(self, ticker: str, shares: float, price: float, dt: date) -> None:
        self.positions[ticker] = Position(
            ticker=ticker, shares=shares, entry_price=price, entry_date=dt
        )

    def close_position(self, ticker: str, price: float, dt: date, commission: float = 0.0) -> float:
        """Close a position and return the realised PnL."""
        pos = self.positions.pop(ticker, None)
        if pos is None:
            return 0.0
        proceeds = pos.shares * price - commission
        cost = pos.shares * pos.entry_price
        pnl = proceeds - cost
        self.cash += proceeds
        self.trades.append(
            {
                "date": dt.isoformat(),
                "ticker": ticker,
                "action": "sell",
                "shares": pos.shares,
                "price": price,
                "commission": commission,
                "pnl": pnl,
            }
        )
        return pnl
