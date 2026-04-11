"""Portfolio simulator — applies signals to a notional portfolio."""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.backtest.engine import BacktestEngine
from app.services.signals.base import BaseStrategy


def simulate_portfolio(
    price_data: dict[str, pd.DataFrame],
    strategy: BaseStrategy,
    initial_capital: float = 100_000.0,
    commission_bps: float = 10.0,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Run a portfolio simulation using the backtest engine.

    Returns:
        Dict with equity_curve, trades, metrics, and latest positions snapshot.
    """
    engine = BacktestEngine(
        price_data=price_data,
        strategy=strategy,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        date_from=date_from,
        date_to=date_to,
    )
    result = engine.run()

    # Build latest positions snapshot from the equity curve endpoint
    last_date = date_to or (date.today() if not price_data else max(
        df.index.max() for df in price_data.values() if len(df) > 0
    ))
    result["snapshot_date"] = last_date.isoformat() if hasattr(last_date, "isoformat") else str(last_date)
    return result
