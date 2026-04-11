"""Position sizing functions.

All functions are pure — no database or framework dependencies.
"""
from __future__ import annotations


def fixed_fractional_size(
    capital: float,
    price: float,
    risk_per_trade: float = 0.01,
    stop_distance: float | None = None,
) -> int:
    """Calculate position size using fixed-fractional method.

    If stop_distance is provided, size is risk_amount / stop_distance.
    Otherwise, size is (capital * risk_per_trade) / price.

    Args:
        capital: Available capital.
        price: Current asset price.
        risk_per_trade: Fraction of capital to risk per trade (e.g. 0.01 = 1%).
        stop_distance: Distance in price units to stop-loss (optional).

    Returns:
        Integer number of shares to buy (minimum 0).
    """
    if price <= 0:
        return 0
    risk_amount = capital * risk_per_trade
    if stop_distance and stop_distance > 0:
        shares = risk_amount / stop_distance
    else:
        shares = risk_amount / price
    return max(0, int(shares))


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly criterion fraction of capital to bet.

    Args:
        win_rate: Probability of winning (0-1).
        avg_win: Average gain per winning trade (as a fraction, e.g. 0.05 = 5%).
        avg_loss: Average loss per losing trade (as a positive fraction, e.g. 0.03 = 3%).

    Returns:
        Kelly fraction (0-1), clamped to [0, 1].
    """
    if avg_loss <= 0:
        return 0.0
    odds = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / odds
    return max(0.0, min(1.0, kelly))
