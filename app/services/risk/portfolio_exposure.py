"""Portfolio-level risk controls."""
from __future__ import annotations


def max_position_weight(
    position_value: float,
    portfolio_nav: float,
    max_weight: float = 0.10,
) -> bool:
    """Check whether a position exceeds the maximum allowed weight.

    Args:
        position_value: Current market value of the position.
        portfolio_nav: Total portfolio net asset value.
        max_weight: Maximum allowed weight as a fraction (e.g. 0.10 = 10%).

    Returns:
        True if the position is within limits, False if it exceeds them.
    """
    if portfolio_nav <= 0:
        return False
    return (position_value / portfolio_nav) <= max_weight


def max_open_positions(current_count: int, max_positions: int = 10) -> bool:
    """Check whether the number of open positions is within the limit.

    Returns:
        True if a new position can be opened.
    """
    return current_count < max_positions


def portfolio_heat(
    open_risks: list[float],
    max_heat: float = 0.06,
) -> bool:
    """Check whether total portfolio risk (sum of per-trade risks) is within limit.

    Args:
        open_risks: List of per-trade risk fractions (e.g. [0.01, 0.01, 0.01]).
        max_heat: Maximum total risk as a fraction of capital.

    Returns:
        True if the portfolio heat is within the limit.
    """
    return sum(open_risks) <= max_heat


def compute_sector_exposure(
    positions: list[dict],
) -> dict[str, float]:
    """Compute sector exposure weights from a list of positions.

    Each position dict must have: ticker, weight, sector (optional).

    Returns:
        Dict mapping sector -> total weight.
    """
    exposure: dict[str, float] = {}
    for pos in positions:
        sector = pos.get("sector", "unknown")
        exposure[sector] = exposure.get(sector, 0.0) + pos.get("weight", 0.0)
    return exposure
