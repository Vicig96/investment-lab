"""Registry of all available signal strategies."""
from __future__ import annotations

from app.services.signals.base import BaseStrategy
from app.services.signals.ma_crossover import MACrossoverStrategy
from app.services.signals.relative_momentum import RelativeMomentumStrategy
from app.services.signals.trend_filter import TrendFilterStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "ma_crossover": MACrossoverStrategy,
    "relative_momentum": RelativeMomentumStrategy,
    "trend_filter": TrendFilterStrategy,
}


def get_strategy(name: str, **params) -> BaseStrategy:
    """Instantiate a strategy by name.

    Raises:
        KeyError: If the strategy name is not in the registry.
    """
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        available = sorted(STRATEGY_REGISTRY.keys())
        raise KeyError(f"Unknown strategy '{name}'. Available: {available}")
    return cls(**params)


def list_strategies() -> list[dict]:
    return [
        {
            "name": cls.name,
            "description": cls.description,
            "params": cls.default_params,
        }
        for cls in STRATEGY_REGISTRY.values()
    ]
