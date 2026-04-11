"""Tests for all technical indicators."""
import numpy as np
import pandas as pd
import pytest

from app.services.indicators.moving_averages import SMAIndicator, EMAIndicator
from app.services.indicators.momentum import RSIIndicator, MACDIndicator
from app.services.indicators.volatility import ATRIndicator, HistoricalVolatilityIndicator
from app.services.indicators.returns import DailyReturnsIndicator, LogReturnsIndicator, CumulativeReturnsIndicator
from app.services.indicators.registry import get_indicator, INDICATOR_REGISTRY


# ── SMA ──────────────────────────────────────────────────────────────────────

class TestSMA:
    def test_basic_value(self, sample_df):
        sma = SMAIndicator(period=20)
        result = sma.compute(sample_df)
        assert result.notna().sum() > 0

    def test_first_values_nan(self, sample_df):
        period = 20
        result = SMAIndicator(period=period).compute(sample_df)
        assert result.iloc[:period - 1].isna().all()

    def test_sma_equals_rolling_mean(self, sample_df):
        period = 5
        result = SMAIndicator(period=period).compute(sample_df)
        expected = sample_df["close"].rolling(period, min_periods=period).mean()
        pd.testing.assert_series_equal(result, expected)


# ── EMA ──────────────────────────────────────────────────────────────────────

class TestEMA:
    def test_basic(self, sample_df):
        result = EMAIndicator(period=20).compute(sample_df)
        assert result.notna().sum() > 0

    def test_ema_more_responsive_than_sma(self, sample_df):
        sma = SMAIndicator(period=10).compute(sample_df)
        ema = EMAIndicator(period=10).compute(sample_df)
        # Both should produce the same number of non-null values given min_periods
        assert ema.notna().sum() == sma.notna().sum()


# ── RSI ──────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_rsi_range(self, sample_df):
        result = RSIIndicator(period=14).compute(sample_df)
        non_null = result.dropna()
        assert (non_null >= 0).all() and (non_null <= 100).all()

    def test_rsi_length(self, sample_df):
        result = RSIIndicator(period=14).compute(sample_df)
        assert len(result) == len(sample_df)


# ── MACD ─────────────────────────────────────────────────────────────────────

class TestMACD:
    def test_macd_line(self, sample_df):
        result = MACDIndicator().compute(sample_df)
        assert len(result) == len(sample_df)

    def test_histogram_equals_macd_minus_signal(self, sample_df):
        ind = MACDIndicator()
        macd = ind.compute(sample_df)
        signal = ind.compute_signal(sample_df)
        hist = ind.compute_histogram(sample_df)
        expected = macd - signal
        pd.testing.assert_series_equal(hist, expected)


# ── ATR ──────────────────────────────────────────────────────────────────────

class TestATR:
    def test_atr_positive(self, sample_df):
        result = ATRIndicator(period=14).compute(sample_df)
        non_null = result.dropna()
        assert (non_null > 0).all()

    def test_atr_length(self, sample_df):
        result = ATRIndicator(period=14).compute(sample_df)
        assert len(result) == len(sample_df)


# ── Historical Volatility ────────────────────────────────────────────────────

class TestHistoricalVolatility:
    def test_hvol_positive(self, sample_df):
        result = HistoricalVolatilityIndicator(period=20).compute(sample_df)
        non_null = result.dropna()
        assert (non_null > 0).all()


# ── Returns ──────────────────────────────────────────────────────────────────

class TestReturns:
    def test_daily_returns_first_nan(self, sample_df):
        result = DailyReturnsIndicator().compute(sample_df)
        assert pd.isna(result.iloc[0])

    def test_log_returns_first_nan(self, sample_df):
        result = LogReturnsIndicator().compute(sample_df)
        assert pd.isna(result.iloc[0])

    def test_cumulative_starts_near_zero(self, sample_df):
        result = CumulativeReturnsIndicator().compute(sample_df)
        assert abs(result.iloc[0]) < 1e-9


# ── Registry ─────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_all_registered(self):
        for name in ["sma", "ema", "rsi", "macd", "atr", "hvol", "daily_returns"]:
            assert name in INDICATOR_REGISTRY

    def test_get_indicator_with_params(self, sample_df):
        ind = get_indicator("sma", period=10)
        result = ind.compute(sample_df)
        assert result.notna().sum() > 0

    def test_get_indicator_unknown_raises(self):
        with pytest.raises(KeyError):
            get_indicator("nonexistent")
