"""Trend Filter strategy — price vs long-term moving average."""
from __future__ import annotations

import pandas as pd

from app.services.signals.base import BaseStrategy
from app.services.indicators.moving_averages import SMAIndicator


class TrendFilterStrategy(BaseStrategy):
    """Long only when price is above long-term MA; flat when below."""

    name = "trend_filter"
    description = "Long when close > long-term SMA, flat otherwise (trend following filter)."
    default_params = {"period": 200}

    def __init__(self, period: int = 200) -> None:
        super().__init__(period=period)
        self.period = period

    def generate(self, df: pd.DataFrame) -> pd.Series:
        long_ma = SMAIndicator(period=self.period).compute(df)

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[df["close"] > long_ma] = 1
        return signal
