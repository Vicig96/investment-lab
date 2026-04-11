"""Tests for signal strategies."""
import pandas as pd
import pytest

from app.services.signals.ma_crossover import MACrossoverStrategy
from app.services.signals.relative_momentum import RelativeMomentumStrategy
from app.services.signals.trend_filter import TrendFilterStrategy
from app.services.signals.registry import get_strategy, STRATEGY_REGISTRY


class TestMACrossover:
    def test_values_are_0_or_1(self, sample_df):
        strat = MACrossoverStrategy(fast=10, slow=30)
        result = strat.generate(sample_df)
        assert set(result.unique()).issubset({0, 1})

    def test_correct_length(self, sample_df):
        result = MACrossoverStrategy().generate(sample_df)
        assert len(result) == len(sample_df)

    def test_ema_type(self, sample_df):
        result = MACrossoverStrategy(fast=10, slow=30, ma_type="ema").generate(sample_df)
        assert set(result.unique()).issubset({0, 1})


class TestRelativeMomentum:
    def test_values_are_minus1_0_1(self, sample_df):
        result = RelativeMomentumStrategy(lookback=20).generate(sample_df)
        assert set(result.unique()).issubset({-1, 0, 1})

    def test_correct_length(self, sample_df):
        result = RelativeMomentumStrategy().generate(sample_df)
        assert len(result) == len(sample_df)


class TestTrendFilter:
    def test_values_are_0_or_1(self, sample_df):
        result = TrendFilterStrategy(period=50).generate(sample_df)
        assert set(result.unique()).issubset({0, 1})

    def test_long_period_all_flat_at_start(self, sample_df):
        period = 200
        result = TrendFilterStrategy(period=period).generate(sample_df)
        # First (period-1) values should be 0 because SMA is NaN
        assert (result.iloc[:period - 1] == 0).all()


class TestStrategyRegistry:
    def test_all_strategies_registered(self):
        for name in ["ma_crossover", "relative_momentum", "trend_filter"]:
            assert name in STRATEGY_REGISTRY

    def test_get_strategy_with_params(self, sample_df):
        strat = get_strategy("ma_crossover", fast=5, slow=20)
        result = strat.generate(sample_df)
        assert len(result) == len(sample_df)

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError):
            get_strategy("does_not_exist")
