"""Backtest performance metrics.

Pure functions — only numpy/pandas, no app dependencies.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(equity_curve: list[dict], trading_days: int = 252) -> float | None:
    """Compound Annual Growth Rate.

    Args:
        equity_curve: List of {"date": "YYYY-MM-DD", "equity": float}.
        trading_days: Number of trading days per year.

    Returns:
        CAGR as a decimal (0.10 = 10%) or None if insufficient data.
    """
    if len(equity_curve) < 2:
        return None
    equities = [p["equity"] for p in equity_curve]
    start, end = equities[0], equities[-1]
    if start <= 0:
        return None
    n_years = len(equity_curve) / trading_days
    if n_years <= 0:
        return None
    return (end / start) ** (1 / n_years) - 1


def max_drawdown(equity_curve: list[dict]) -> float | None:
    """Maximum drawdown as a negative fraction.

    Returns:
        Maximum drawdown (e.g. -0.25 means -25%) or None if no data.
    """
    if not equity_curve:
        return None
    equities = np.array([p["equity"] for p in equity_curve], dtype=float)
    running_max = np.maximum.accumulate(equities)
    drawdowns = (equities - running_max) / running_max
    return float(drawdowns.min())


def sharpe_ratio(
    equity_curve: list[dict],
    risk_free_rate: float = 0.0,
    trading_days: int = 252,
) -> float | None:
    """Annualised Sharpe ratio.

    Args:
        equity_curve: List of {"date": ..., "equity": float}.
        risk_free_rate: Annual risk-free rate (e.g. 0.05 = 5%).
        trading_days: Trading days per year for annualisation.

    Returns:
        Sharpe ratio or None if insufficient data.
    """
    if len(equity_curve) < 2:
        return None
    equities = np.array([p["equity"] for p in equity_curve], dtype=float)
    daily_returns = np.diff(equities) / equities[:-1]
    daily_rf = risk_free_rate / trading_days
    excess = daily_returns - daily_rf
    std = excess.std()
    if std == 0:
        return None
    return float((excess.mean() / std) * np.sqrt(trading_days))


def calmar_ratio(equity_curve: list[dict], trading_days: int = 252) -> float | None:
    """Calmar ratio: CAGR / abs(max drawdown)."""
    c = cagr(equity_curve, trading_days)
    md = max_drawdown(equity_curve)
    if c is None or md is None or md == 0:
        return None
    return c / abs(md)


def win_rate(trades: list[dict]) -> float | None:
    """Fraction of closed trades that were profitable.

    Args:
        trades: List of trade dicts with 'pnl' key.

    Returns:
        Win rate as a decimal (0.0–1.0) or None if no closed trades.
    """
    closed = [t for t in trades if t.get("pnl") is not None]
    if not closed:
        return None
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return wins / len(closed)


def compute_all_metrics(equity_curve: list[dict], trades: list[dict]) -> dict:
    """Compute all metrics in one call."""
    return {
        "cagr": cagr(equity_curve),
        "max_drawdown": max_drawdown(equity_curve),
        "sharpe_ratio": sharpe_ratio(equity_curve),
        "calmar_ratio": calmar_ratio(equity_curve),
        "win_rate": win_rate(trades),
        "total_trades": len([t for t in trades if t.get("action") == "sell"]),
        "final_equity": equity_curve[-1]["equity"] if equity_curve else None,
    }
