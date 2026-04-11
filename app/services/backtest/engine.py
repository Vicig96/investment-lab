"""Backtest engine — drives the simulation loop."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.core.logging import get_logger
from app.services.backtest.broker import SimulatedBroker
from app.services.backtest.metrics import compute_all_metrics
from app.services.backtest.portfolio_state import PortfolioState
from app.services.signals.base import BaseStrategy

logger = get_logger(__name__)


class BacktestEngine:
    """Event-driven daily backtest engine.

    Usage:
        engine = BacktestEngine(
            price_data={"AAPL": df_aapl, "MSFT": df_msft},
            strategy=MACrossoverStrategy(fast=20, slow=50),
            initial_capital=100_000,
            commission_bps=10,
        )
        result = engine.run()
    """

    def __init__(
        self,
        price_data: dict[str, pd.DataFrame],
        strategy: BaseStrategy,
        initial_capital: float = 100_000.0,
        commission_bps: float = 10.0,
        risk_per_trade: float = 0.01,
        stop_pct: float = 0.02,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> None:
        self.price_data = price_data
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.commission_bps = commission_bps
        self.risk_per_trade = risk_per_trade
        self.stop_pct = stop_pct
        self.date_from = date_from
        self.date_to = date_to

    def run(self) -> dict:
        """Execute the backtest and return a result dict.

        Returns:
            Dict with keys: equity_curve, trades, metrics.
        """
        state = PortfolioState(initial_capital=self.initial_capital)
        broker = SimulatedBroker(commission_bps=self.commission_bps)

        # Build a unified sorted timeline of all dates across all instruments
        all_dates: set[date] = set()
        for df in self.price_data.values():
            all_dates.update(df.index.tolist())

        sorted_dates = sorted(all_dates)
        if self.date_from:
            sorted_dates = [d for d in sorted_dates if d >= self.date_from]
        if self.date_to:
            sorted_dates = [d for d in sorted_dates if d <= self.date_to]

        # Pre-compute signals for each instrument up to each date
        # For efficiency, compute once and slice by date in the loop
        signals_cache: dict[str, pd.Series] = {}
        for ticker, df in self.price_data.items():
            filtered = df
            if self.date_from:
                filtered = filtered[filtered.index >= self.date_from]
            if self.date_to:
                filtered = filtered[filtered.index <= self.date_to]
            if len(filtered) > 0:
                signals_cache[ticker] = self.strategy.generate(filtered)

        for dt in sorted_dates:
            prices_today: dict[str, float] = {}
            for ticker, df in self.price_data.items():
                if dt in df.index:
                    prices_today[ticker] = float(df.loc[dt, "close"])

            if not prices_today:
                continue

            # Evaluate signals
            for ticker, signal_series in signals_cache.items():
                if dt not in signal_series.index:
                    continue
                signal_value = int(signal_series.loc[dt])
                price = prices_today.get(ticker)
                if price is None:
                    continue

                if signal_value == 1 and ticker not in state.positions:
                    broker.fill_buy(
                        state, ticker, price, dt,
                        risk_per_trade=self.risk_per_trade,
                        stop_pct=self.stop_pct,
                    )
                elif signal_value == 0 and ticker in state.positions:
                    broker.fill_sell(state, ticker, price, dt)
                elif signal_value == -1 and ticker in state.positions:
                    broker.fill_sell(state, ticker, price, dt)

            state.record_equity(dt, prices_today)

        metrics = compute_all_metrics(state.equity_curve, state.trades)
        logger.info(
            "backtest_complete",
            strategy=self.strategy.name,
            tickers=list(self.price_data.keys()),
            final_equity=metrics.get("final_equity"),
        )
        return {
            "equity_curve": state.equity_curve,
            "trades": state.trades,
            "metrics": metrics,
        }
