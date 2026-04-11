"""Simulated broker — fills orders on historical prices with commissions.

NO connection to any real brokerage. Simulation only.
"""
from __future__ import annotations

from datetime import date

from app.services.backtest.portfolio_state import PortfolioState
from app.services.risk.position_sizing import fixed_fractional_size


class SimulatedBroker:
    def __init__(self, commission_bps: float = 10.0) -> None:
        """
        Args:
            commission_bps: Commission in basis points applied to trade notional.
        """
        self.commission_bps = commission_bps

    def _commission(self, notional: float) -> float:
        return notional * (self.commission_bps / 10_000)

    def fill_buy(
        self,
        state: PortfolioState,
        ticker: str,
        price: float,
        dt: date,
        risk_per_trade: float = 0.01,
        stop_pct: float = 0.02,
    ) -> bool:
        """Open a long position sized by fixed-fractional method.

        Returns:
            True if the order was filled, False if insufficient capital.
        """
        if ticker in state.positions:
            return False  # already open

        stop_distance = price * stop_pct
        shares = fixed_fractional_size(
            capital=state.cash,
            price=price,
            risk_per_trade=risk_per_trade,
            stop_distance=stop_distance,
        )
        if shares == 0:
            return False

        notional = shares * price
        commission = self._commission(notional)
        total_cost = notional + commission

        if total_cost > state.cash:
            # Scale down to what we can afford
            affordable_notional = state.cash / (1 + self.commission_bps / 10_000)
            shares = max(0, int(affordable_notional / price))
            if shares == 0:
                return False
            notional = shares * price
            commission = self._commission(notional)
            total_cost = notional + commission

        state.cash -= total_cost
        state.open_position(ticker, shares, price, dt)
        state.trades.append(
            {
                "date": dt.isoformat(),
                "ticker": ticker,
                "action": "buy",
                "shares": shares,
                "price": price,
                "commission": commission,
                "pnl": None,
            }
        )
        return True

    def fill_sell(
        self,
        state: PortfolioState,
        ticker: str,
        price: float,
        dt: date,
    ) -> bool:
        """Close a long position.

        Returns:
            True if filled, False if no position exists.
        """
        if ticker not in state.positions:
            return False
        pos = state.positions[ticker]
        commission = self._commission(pos.shares * price)
        state.close_position(ticker, price, dt, commission)
        return True
