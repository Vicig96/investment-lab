"""Simple and Exponential Moving Average indicators."""
from __future__ import annotations

import pandas as pd

from app.services.indicators.base import BaseIndicator


class SMAIndicator(BaseIndicator):
    name = "sma"
    description = "Simple Moving Average"
    default_params = {"period": 20}

    def __init__(self, period: int = 20) -> None:
        super().__init__(period=period)
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].rolling(window=self.period, min_periods=self.period).mean()


class EMAIndicator(BaseIndicator):
    name = "ema"
    description = "Exponential Moving Average"
    default_params = {"period": 20}

    def __init__(self, period: int = 20) -> None:
        super().__init__(period=period)
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].ewm(span=self.period, adjust=False, min_periods=self.period).mean()
