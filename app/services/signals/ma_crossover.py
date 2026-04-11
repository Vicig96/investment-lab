"""Moving Average Crossover strategy."""
from __future__ import annotations

import pandas as pd

from app.services.signals.base import BaseStrategy
from app.services.indicators.moving_averages import SMAIndicator, EMAIndicator


class MACrossoverStrategy(BaseStrategy):
    """Go long when fast MA crosses above slow MA; exit when it crosses below."""

    name = "ma_crossover"
    description = "Moving average crossover: long when fast > slow, flat otherwise."
    default_params = {"fast": 20, "slow": 50, "ma_type": "sma"}

    def __init__(self, fast: int = 20, slow: int = 50, ma_type: str = "sma") -> None:
        super().__init__(fast=fast, slow=slow, ma_type=ma_type)
        self.fast = fast
        self.slow = slow
        self.ma_type = ma_type

    def _ma(self, df: pd.DataFrame, period: int) -> pd.Series:
        if self.ma_type == "ema":
            return EMAIndicator(period=period).compute(df)
        return SMAIndicator(period=period).compute(df)

    def generate(self, df: pd.DataFrame) -> pd.Series:
        fast_ma = self._ma(df, self.fast)
        slow_ma = self._ma(df, self.slow)

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[fast_ma > slow_ma] = 1
        return signal
