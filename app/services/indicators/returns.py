"""Return-based indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.indicators.base import BaseIndicator


class DailyReturnsIndicator(BaseIndicator):
    name = "daily_returns"
    description = "Simple daily returns (percentage change)"
    default_params = {}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change()


class LogReturnsIndicator(BaseIndicator):
    name = "log_returns"
    description = "Log daily returns"
    default_params = {}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return np.log(df["close"] / df["close"].shift(1))


class CumulativeReturnsIndicator(BaseIndicator):
    name = "cumulative_returns"
    description = "Cumulative simple returns"
    default_params = {}

    def compute(self, df: pd.DataFrame) -> pd.Series:
        daily = df["close"].pct_change().fillna(0)
        return (1 + daily).cumprod() - 1
