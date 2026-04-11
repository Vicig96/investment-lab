"""Relative Momentum strategy (single-instrument lookback momentum)."""
from __future__ import annotations

import pandas as pd

from app.services.signals.base import BaseStrategy


class RelativeMomentumStrategy(BaseStrategy):
    """Go long if the n-period return is positive, flat/short otherwise."""

    name = "relative_momentum"
    description = "Long if n-period return is positive; short if negative; flat if near zero."
    default_params = {"lookback": 20, "threshold": 0.0}

    def __init__(self, lookback: int = 20, threshold: float = 0.0) -> None:
        super().__init__(lookback=lookback, threshold=threshold)
        self.lookback = lookback
        self.threshold = threshold

    def generate(self, df: pd.DataFrame) -> pd.Series:
        momentum = df["close"].pct_change(periods=self.lookback)

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[momentum > self.threshold] = 1
        signal[momentum < -self.threshold] = -1
        return signal
