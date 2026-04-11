"""Abstract base for all technical indicators."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseIndicator(ABC):
    """All indicators take a pd.DataFrame (OHLCV) and return a pd.Series."""

    name: str = ""
    description: str = ""
    default_params: dict = {}

    def __init__(self, **params) -> None:
        self.params = {**self.default_params, **params}

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Compute the indicator.

        Args:
            df: DataFrame with columns [open, high, low, close, volume] indexed by date.

        Returns:
            pd.Series indexed by date with computed values.
        """
        ...

    def param_fingerprint(self) -> dict:
        return self.params.copy()
