"""Registry of all available indicators.

This dict is the single source of truth for the API and the LLM tool-calling layer.
"""
from __future__ import annotations

from app.services.indicators.base import BaseIndicator
from app.services.indicators.moving_averages import SMAIndicator, EMAIndicator
from app.services.indicators.momentum import RSIIndicator, MACDIndicator
from app.services.indicators.volatility import ATRIndicator, HistoricalVolatilityIndicator
from app.services.indicators.returns import DailyReturnsIndicator, LogReturnsIndicator, CumulativeReturnsIndicator

INDICATOR_REGISTRY: dict[str, type[BaseIndicator]] = {
    "sma": SMAIndicator,
    "ema": EMAIndicator,
    "rsi": RSIIndicator,
    "macd": MACDIndicator,
    "atr": ATRIndicator,
    "hvol": HistoricalVolatilityIndicator,
    "daily_returns": DailyReturnsIndicator,
    "log_returns": LogReturnsIndicator,
    "cumulative_returns": CumulativeReturnsIndicator,
}


def get_indicator(name: str, **params) -> BaseIndicator:
    """Instantiate an indicator by name with given params.

    Raises:
        KeyError: If the indicator name is not in the registry.
    """
    cls = INDICATOR_REGISTRY.get(name)
    if cls is None:
        available = sorted(INDICATOR_REGISTRY.keys())
        raise KeyError(f"Unknown indicator '{name}'. Available: {available}")
    return cls(**params)


def list_indicators() -> list[dict]:
    return [
        {
            "name": cls.name,
            "description": cls.description,
            "params": cls.default_params,
        }
        for cls in INDICATOR_REGISTRY.values()
    ]
