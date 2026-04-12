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
Both sells and buys execute at the **close price on the rebalance date**.
The screener is computed with data that includes that same close, making
this a same-bar execution assumption (common in daily-bar backtests).
This is a known V1 simplification — documented here rather than hidden.

Assumptions
-----------
* Fractional shares are allowed (this is a backtester, not a live broker).
* Commission is applied one-way to the notional trade value.
* If a ticker has no price on a rebalance date it is excluded that period.
* Cash earns no interest.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.services.backtest.metrics import compute_all_metrics
from app.services.screener.scorer import score_universe

# Eligibility mirrors the screener endpoint eligibility filter
_ELIGIBLE_LABELS   = {"BUY", "WATCH"}
_ELIGIBLE_QUALITY  = {"GOOD", "LIMITED"}


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
) -> dict:
    """Run a monthly screener rotation backtest.

    Args:
        dfs:              Full OHLCV history per ticker (date index, close required).
                          May include pre-period warm-up bars before eval_start_date.
        top_n:            Maximum assets to hold per rebalance period.
        initial_capital:  Starting cash in account currency.
        commission_bps:   One-way commission as basis points (10 = 0.10 %).
        eval_start_date:  First date that counts toward reported performance.
                          Dates before this are used only for indicator warm-up;
                          no trades are recorded and equity is not tracked.
                          If None, all dates are included in the evaluation window.

    Returns:
        dict with keys: equity_curve, rebalance_log, holdings_by_rebalance,
                        trades, metrics, warmup_bars_available
    """
    commission_rate = commission_bps / 10_000

    # ── Union of all trading dates present in the filtered range ─────────────
    all_dates: list[date] = sorted(
        set().union(*(set(df.index) for df in dfs.values()))
    )

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

    # Number of trading days that fall before the evaluation window
    warmup_bars_available: int = (
        sum(1 for d in all_dates if d < eval_start_date)
        if eval_start_date is not None
        else 0
    )

    # Pre-build O(1) membership lookup per ticker
    date_sets: dict[str, frozenset] = {
        t: frozenset(df.index) for t, df in dfs.items()
    }

    # ── Monthly rebalance dates: first trading day of each calendar month ────
    rebalance_dates: set[date] = set()
    prev_month: int | None = None
    for d in all_dates:
        if d.month != prev_month:
            rebalance_dates.add(d)
            prev_month = d.month

    # ── Simulation state ──────────────────────────────────────────────────────
    cash = float(initial_capital)
    holdings: dict[str, float] = {}   # ticker → fractional shares held
    equity_curve: list[dict] = []
    rebalance_log: list[dict] = []
    trades: list[dict] = []

    for current_date in all_dates:

        # Skip warm-up period — these dates provide indicator history only;
        # no trades are made and no equity snapshots are recorded.
        if eval_start_date is not None and current_date < eval_start_date:
            continue

        # Close prices available on this date (only tickers that traded)
        prices: dict[str, float] = {
            t: float(dfs[t].at[current_date, "close"])
            for t in dfs
            if current_date in date_sets[t]
        }

        # ── Rebalance ─────────────────────────────────────────────────────────
        if current_date in rebalance_dates:

            # Portfolio value before executing any trades
            portfolio_value = cash + sum(
                shares * prices.get(t, 0.0)
                for t, shares in holdings.items()
            )

            # Point-in-time screener: slice each DataFrame to [start, current_date]
            slice_dfs = {
                t: df[df.index <= current_date]
                for t, df in dfs.items()
                if not df[df.index <= current_date].empty
            }
            _, ranked = score_universe(slice_dfs, top_n)

            # Eligible assets: correct label, sufficient quality, have a price today
            eligible = [
                r for r in ranked
                if r["label"]        in _ELIGIBLE_LABELS
                and r["data_quality"] in _ELIGIBLE_QUALITY
                and r["ticker"]       in prices
            ][:top_n]

            # Build target weights from screener output
            new_weights: dict[str, float] = {
                r["ticker"]: (r.get("suggested_weight") or 0.0)
                for r in eligible
                if (r.get("suggested_weight") or 0.0) > 0
            }

            # Renormalise only if cap-rounding pushed sum meaningfully off 1.0
            total_w = sum(new_weights.values())
            if total_w > 0 and not (0.999 <= total_w <= 1.001):
                new_weights = {t: w / total_w for t, w in new_weights.items()}

            # ── Sell all current holdings ──────────────────────────────────────
            for ticker, shares in list(holdings.items()):
                price = prices.get(ticker, 0.0)
                if price <= 0 or shares <= 0:
                    continue
                sell_value = shares * price
                commission = sell_value * commission_rate
                cash += sell_value - commission
                trades.append({
                    "date":       str(current_date),
                    "ticker":     ticker,
                    "action":     "sell",
                    "shares":     round(shares, 6),
                    "price":      round(price, 4),
                    "commission": round(commission, 4),
                    "pnl":        None,
                })
            holdings = {}

            # ── Buy new holdings ───────────────────────────────────────────────
            for ticker, weight in new_weights.items():
                price = prices.get(ticker, 0.0)
                if price <= 0 or weight <= 0:
                    continue
                target_value = portfolio_value * weight
                shares        = target_value / price
                commission    = target_value * commission_rate
                cash         -= target_value + commission
                holdings[ticker] = shares
                trades.append({
                    "date":       str(current_date),
                    "ticker":     ticker,
                    "action":     "buy",
                    "shares":     round(shares, 6),
                    "price":      round(price, 4),
                    "commission": round(commission, 4),
                    "pnl":        None,
                })

            rebalance_log.append({
                "date":              str(current_date),
                "eligible_count":    len(eligible),
                "cash_only":         len(new_weights) == 0,
                "selected_tickers":  list(new_weights.keys()),
                "weights":           {t: round(w, 4) for t, w in new_weights.items()},
            })

        # ── Daily equity snapshot (end of day) ────────────────────────────────
        equity = cash + sum(
            shares * prices.get(t, 0.0)
            for t, shares in holdings.items()
        )
        equity_curve.append({
            "date":   str(current_date),
            "equity": round(float(equity), 2),
        })

    # ── Post-simulation ───────────────────────────────────────────────────────
    holdings_by_rebalance = [
        {"date": r["date"], "holdings": r["weights"]}
        for r in rebalance_log
    ]

    metrics = compute_all_metrics(equity_curve, trades)

    return {
        "equity_curve":          equity_curve,
        "rebalance_log":         rebalance_log,
        "holdings_by_rebalance": holdings_by_rebalance,
        "trades":                trades,
        "metrics":               metrics,
        "warmup_bars_available": warmup_bars_available,
    }
