"""Screener rotation strategy backtest engine.

Strategy
--------
On the first trading day of each calendar month (rebalance date):

  1. Slice all DataFrames to data up to and including that date
     (point-in-time: no future information leaks in).
  2. Run the screener scorer on the slice.
  3. Keep assets with label in {BUY, WATCH} and data_quality in {GOOD, LIMITED}.
  4. Take the top_n by score; use their suggested_weight as portfolio weights.
  5. Sell all existing holdings at the day's close price.
  6. Buy new holdings at the day's close price.
  7. Hold until the next rebalance date.

If no eligible assets exist on a rebalance date the strategy stays fully
in cash until the next rebalance.

Execution price
---------------
Both sells and buys execute at the close price on the rebalance date.
The screener is computed with data that includes that same close, making
this a same-bar execution assumption (common in daily-bar backtests).
This is a known V1 simplification and is documented here explicitly.

Assumptions
-----------
* Fractional shares are allowed (this is a backtester, not a live broker).
* Commission is applied one-way to the notional trade value.
* Cash earns no interest.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.backtest.metrics import compute_all_metrics
from app.services.screener.scorer import score_universe

# Eligibility mirrors the screener endpoint eligibility filter.
_ELIGIBLE_LABELS = {"BUY", "WATCH"}
_ELIGIBLE_QUALITY = {"GOOD", "LIMITED"}
_EPSILON = 1e-9


def _portfolio_value(
    cash: float,
    holdings: dict[str, float],
    price_lookup: dict[str, float],
) -> float:
    """Portfolio NAV from cash plus marked-to-market holdings."""
    missing_prices = [
        ticker
        for ticker, shares in holdings.items()
        if shares > 0 and price_lookup.get(ticker, 0.0) <= 0
    ]
    if missing_prices:
        missing = ", ".join(sorted(missing_prices))
        raise ValueError(f"Missing valuation price for held tickers: {missing}")

    equity = float(cash) + sum(
        float(shares) * float(price_lookup[ticker])
        for ticker, shares in holdings.items()
    )
    if equity < -1e-6:
        raise ValueError(f"Portfolio equity became negative: {equity:.6f}")
    return equity


def run_buy_and_hold_benchmark(
    benchmark_df: pd.DataFrame,
    initial_capital: float,
    commission_bps: float,
    eval_start_date: date,
    eval_end_date: date | None = None,
) -> dict:
    """Run a simple buy-and-hold benchmark on one ticker."""
    commission_rate = commission_bps / 10_000

    benchmark_slice = benchmark_df[benchmark_df.index >= eval_start_date]
    if eval_end_date is not None:
        benchmark_slice = benchmark_slice[benchmark_slice.index <= eval_end_date]
    benchmark_slice = benchmark_slice.sort_index()

    if benchmark_slice.empty:
        return {
            "equity_curve": [],
            "metrics": compute_all_metrics([], []),
        }

    first_close = float(benchmark_slice.iloc[0]["close"])
    if first_close <= 0:
        return {
            "equity_curve": [],
            "metrics": compute_all_metrics([], []),
        }

    shares = float(initial_capital) / (first_close * (1 + commission_rate))
    equity_curve = [
        {
            "date": str(current_date),
            "equity": round(float(shares * float(row["close"])), 2),
        }
        for current_date, row in benchmark_slice.iterrows()
    ]

    return {
        "equity_curve": equity_curve,
        "metrics": compute_all_metrics(equity_curve, []),
    }


def run_rotation(
    dfs: dict[str, pd.DataFrame],
    top_n: int,
    initial_capital: float,
    commission_bps: float,
    eval_start_date: date | None = None,
    defensive_mode: str = "cash",
    defensive_tickers: list[str] | None = None,
) -> dict:
    """Run a monthly screener rotation backtest."""
    commission_rate = commission_bps / 10_000
    defensive_priority = [
        ticker.strip().upper()
        for ticker in (defensive_tickers or [])
        if ticker.strip()
    ]
    defensive_set = set(defensive_priority)

    all_dates: list[date] = sorted(set().union(*(set(df.index) for df in dfs.values())))

    if not all_dates:
        empty_metrics = compute_all_metrics([], [])
        return {
            "equity_curve": [],
            "rebalance_log": [],
            "holdings_by_rebalance": [],
            "trades": [],
            "metrics": empty_metrics,
            "warmup_bars_available": 0,
        }

    warmup_bars_available = (
        sum(1 for current_date in all_dates if current_date < eval_start_date)
        if eval_start_date is not None
        else 0
    )

    date_sets: dict[str, frozenset] = {
        ticker: frozenset(df.index) for ticker, df in dfs.items()
    }

    rebalance_dates: set[date] = set()
    prev_month: int | None = None
    for current_date in all_dates:
        if current_date.month != prev_month:
            rebalance_dates.add(current_date)
            prev_month = current_date.month

    cash = float(initial_capital)
    holdings: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    equity_curve: list[dict] = []
    rebalance_log: list[dict] = []
    trades: list[dict] = []

    for current_date in all_dates:
        if eval_start_date is not None and current_date < eval_start_date:
            continue

        prices: dict[str, float] = {
            ticker: float(dfs[ticker].at[current_date, "close"])
            for ticker in dfs
            if current_date in date_sets[ticker]
        }
        last_prices.update(prices)

        if current_date in rebalance_dates:
            can_rebalance = all(
                shares <= 0 or prices.get(ticker, 0.0) > 0
                for ticker, shares in holdings.items()
            )

            if can_rebalance:
                portfolio_value = _portfolio_value(cash, holdings, last_prices)

                slice_dfs = {
                    ticker: df[df.index <= current_date]
                    for ticker, df in dfs.items()
                    if not df[df.index <= current_date].empty
                }
                _, ranked = score_universe(slice_dfs, top_n)

                risk_on_eligible = [
                    row
                    for row in ranked
                    if row["label"] in _ELIGIBLE_LABELS
                    and row["data_quality"] in _ELIGIBLE_QUALITY
                    and row["ticker"] in prices
                    and row["ticker"] not in defensive_set
                ][:top_n]

                defensive_candidates = {
                    row["ticker"]: row
                    for row in ranked
                    if row["label"] in _ELIGIBLE_LABELS
                    and row["data_quality"] in _ELIGIBLE_QUALITY
                    and row["ticker"] in prices
                    and row["ticker"] in defensive_set
                }

                allocation_mode = "cash"
                selected_tickers: list[str] = []
                new_weights: dict[str, float] = {}

                if risk_on_eligible:
                    allocation_mode = "risk_on"
                    new_weights = {
                        row["ticker"]: float(row.get("suggested_weight") or 0.0)
                        for row in risk_on_eligible
                        if (row.get("suggested_weight") or 0.0) > 0
                    }
                    selected_tickers = list(new_weights.keys())
                elif defensive_mode == "defensive_asset":
                    fallback_ticker = next(
                        (
                            ticker
                            for ticker in defensive_priority
                            if ticker in defensive_candidates
                        ),
                        None,
                    )
                    if fallback_ticker is not None:
                        allocation_mode = "defensive"
                        new_weights = {fallback_ticker: 1.0}
                        selected_tickers = [fallback_ticker]

                total_w = sum(new_weights.values())
                if total_w > 0:
                    new_weights = {ticker: weight / total_w for ticker, weight in new_weights.items()}

                for ticker, shares in list(holdings.items()):
                    price = prices.get(ticker, 0.0)
                    if price <= 0 or shares <= 0:
                        continue
                    sell_value = shares * price
                    commission = sell_value * commission_rate
                    cash += sell_value - commission
                    trades.append({
                        "date": str(current_date),
                        "ticker": ticker,
                        "action": "sell",
                        "shares": round(shares, 6),
                        "price": round(price, 4),
                        "commission": round(commission, 4),
                        "pnl": None,
                    })
                holdings = {}

                gross_buying_power = (
                    cash / (1 + commission_rate)
                    if new_weights
                    else 0.0
                )
                for ticker, weight in new_weights.items():
                    price = prices.get(ticker, 0.0)
                    if price <= 0 or weight <= 0:
                        continue
                    target_value = gross_buying_power * weight
                    shares = target_value / price
                    commission = target_value * commission_rate
                    cash -= target_value + commission
                    holdings[ticker] = shares
                    trades.append({
                        "date": str(current_date),
                        "ticker": ticker,
                        "action": "buy",
                        "shares": round(shares, 6),
                        "price": round(price, 4),
                        "commission": round(commission, 4),
                        "pnl": None,
                    })

                if cash < -1e-6:
                    raise ValueError(
                        f"Rotation backtest produced negative cash {cash:.6f} on {current_date}."
                    )
                if abs(cash) < _EPSILON:
                    cash = 0.0

                post_trade_value = _portfolio_value(cash, holdings, last_prices)
                if post_trade_value - portfolio_value > 1e-4:
                    raise ValueError(
                        "Post-trade portfolio value exceeded pre-trade value unexpectedly."
                    )

                rebalance_log.append({
                    "date": str(current_date),
                    "eligible_count": len(risk_on_eligible),
                    "cash_only": len(new_weights) == 0,
                    "selected_tickers": selected_tickers,
                    "weights": {ticker: round(weight, 4) for ticker, weight in new_weights.items()},
                    "allocation_mode": allocation_mode,
                })

        equity = _portfolio_value(cash, holdings, last_prices)
        equity_curve.append({
            "date": str(current_date),
            "equity": round(float(equity), 2),
        })

    holdings_by_rebalance = [
        {"date": rebalance["date"], "holdings": rebalance["weights"]}
        for rebalance in rebalance_log
    ]

    metrics = compute_all_metrics(equity_curve, trades)

    return {
        "equity_curve": equity_curve,
        "rebalance_log": rebalance_log,
        "holdings_by_rebalance": holdings_by_rebalance,
        "trades": trades,
        "metrics": metrics,
        "warmup_bars_available": warmup_bars_available,
    }
