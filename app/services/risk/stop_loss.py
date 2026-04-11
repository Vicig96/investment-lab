"""Stop-loss calculation functions."""
from __future__ import annotations

import pandas as pd


def percentage_stop(entry_price: float, stop_pct: float = 0.02) -> float:
    """Calculate stop-loss price as a percentage below entry.

    Args:
        entry_price: Price at which the position was entered.
        stop_pct: Percentage below entry to place stop (e.g. 0.02 = 2%).

    Returns:
        Stop-loss price.
    """
    return entry_price * (1 - stop_pct)


def atr_stop(entry_price: float, atr: float, multiplier: float = 2.0) -> float:
    """Calculate stop-loss price as a multiple of ATR below entry.

    Args:
        entry_price: Price at which the position was entered.
        atr: Current ATR value.
        multiplier: Number of ATRs below entry to place stop.

    Returns:
        Stop-loss price.
    """
    return entry_price - (atr * multiplier)


def stop_distance(entry_price: float, stop_price: float) -> float:
    """Return the absolute distance between entry and stop.

    Returns:
        Positive distance in price units.
    """
    return abs(entry_price - stop_price)
