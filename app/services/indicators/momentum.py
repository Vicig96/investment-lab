"""RSI and MACD momentum indicators."""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.services.indicators.base import BaseIndicator


class RSIIndicator(BaseIndicator):
    name = "rsi"
    description = "Relative Strength Index"
    default_params = {"period": 14}

    def __init__(self, period: int = 14) -> None:
        super().__init__(period=period)
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(com=self.period - 1, adjust=False, min_periods=self.period).mean()
        avg_loss = loss.ewm(com=self.period - 1, adjust=False, min_periods=self.period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi


class MACDIndicator(BaseIndicator):
    """Returns MACD line (fast EMA - slow EMA)."""
    name = "macd"
    description = "Moving Average Convergence Divergence (MACD line)"
    default_params = {"fast": 12, "slow": 26, "signal": 9}

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        super().__init__(fast=fast, slow=slow, signal=signal)
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def compute(self, df: pd.DataFrame) -> pd.Series:
        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()
        return ema_fast - ema_slow

    def compute_signal(self, df: pd.DataFrame) -> pd.Series:
        macd_line = self.compute(df)
        return macd_line.ewm(span=self.signal, adjust=False).mean()

    def compute_histogram(self, df: pd.DataFrame) -> pd.Series:
        macd_line = self.compute(df)
        signal_line = self.compute_signal(df)
        return macd_line - signal_line
