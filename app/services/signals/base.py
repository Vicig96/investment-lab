"""Abstract base for all signal strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """A strategy receives an OHLCV DataFrame and returns a Series of direction values.

    Direction values: 1 = long, -1 = short, 0 = flat/exit.
    """

    name: str = ""
    description: str = ""
    default_params: dict = {}

    def __init__(self, **params) -> None:
        self.params = {**self.default_params, **params}

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from OHLCV data.

        Args:
            df: DataFrame indexed by date with OHLCV columns.

        Returns:
            pd.Series of integers (1, -1, 0) indexed by date.
        """
        ...

    def param_fingerprint(self) -> dict:
        return self.params.copy()
