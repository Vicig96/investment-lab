"""ATR and Historical Volatility indicators."""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.services.indicators.base import BaseIndicator


class ATRIndicator(BaseIndicator):
    name = "atr"
    description = "Average True Range"
    default_params = {"period": 14}

    def __init__(self, period: int = 14) -> None:
        super().__init__(period=period)
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        return tr.ewm(com=self.period - 1, adjust=False, min_periods=self.period).mean()


class HistoricalVolatilityIndicator(BaseIndicator):
    """Annualised historical volatility from log returns."""
    name = "hvol"
    description = "Historical Volatility (annualised, log returns)"
    default_params = {"period": 20, "trading_days": 252}

    def __init__(self, period: int = 20, trading_days: int = 252) -> None:
        super().__init__(period=period, trading_days=trading_days)
        self.period = period
        self.trading_days = trading_days

    def compute(self, df: pd.DataFrame) -> pd.Series:
        log_returns = np.log(df["close"] / df["close"].shift(1))
        return log_returns.rolling(window=self.period, min_periods=self.period).std() * np.sqrt(
            self.trading_days
        )
