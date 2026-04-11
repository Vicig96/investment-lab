"""Portfolio rebalancing calculator."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RebalanceOrder:
    ticker: str
    action: str  # "buy" | "sell" | "hold"
    current_weight: float
    target_weight: float
    delta_weight: float
    estimated_shares: float | None = None
    estimated_value: float | None = None


def compute_rebalance_orders(
    current_positions: list[dict],
    target_weights: dict[str, float],
    nav: float,
    prices: dict[str, float],
    threshold: float = 0.01,
) -> list[RebalanceOrder]:
    """Compute rebalance orders to reach target weights.

    Args:
        current_positions: List of dicts: {ticker, shares, value}.
        target_weights: Dict mapping ticker -> target weight (fractions that sum to ≤1).
        nav: Current portfolio NAV.
        prices: Dict mapping ticker -> current price.
        threshold: Minimum weight drift to trigger a trade.

    Returns:
        List of RebalanceOrder objects.
    """
    current_weights: dict[str, float] = {}
    for pos in current_positions:
        ticker = pos["ticker"]
        current_weights[ticker] = pos.get("value", 0.0) / nav if nav > 0 else 0.0

    all_tickers = set(current_weights.keys()) | set(target_weights.keys())
    orders: list[RebalanceOrder] = []

    for ticker in sorted(all_tickers):
        current = current_weights.get(ticker, 0.0)
        target = target_weights.get(ticker, 0.0)
        delta = target - current

        if abs(delta) < threshold:
            action = "hold"
        elif delta > 0:
            action = "buy"
        else:
            action = "sell"

        price = prices.get(ticker)
        estimated_value = abs(delta) * nav if nav > 0 else None
        estimated_shares = (estimated_value / price) if (price and price > 0 and estimated_value is not None) else None

        orders.append(RebalanceOrder(
            ticker=ticker,
            action=action,
            current_weight=round(current, 6),
            target_weight=round(target, 6),
            delta_weight=round(delta, 6),
            estimated_shares=round(estimated_shares, 2) if estimated_shares is not None else None,
            estimated_value=round(estimated_value, 2) if estimated_value is not None else None,
        ))

    return orders
