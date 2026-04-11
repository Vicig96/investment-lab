"""Tests for the backtest engine."""
import pytest
import pandas as pd

from app.services.backtest.engine import BacktestEngine
from app.services.signals.ma_crossover import MACrossoverStrategy
from app.services.signals.trend_filter import TrendFilterStrategy


class TestBacktestEngine:
    def test_run_returns_expected_keys(self, sample_df):
        engine = BacktestEngine(
            price_data={"TEST": sample_df},
            strategy=MACrossoverStrategy(fast=10, slow=30),
            initial_capital=100_000,
        )
        result = engine.run()
        assert "equity_curve" in result
        assert "trades" in result
        assert "metrics" in result

    def test_equity_curve_non_empty(self, sample_df):
        engine = BacktestEngine(
            price_data={"TEST": sample_df},
            strategy=MACrossoverStrategy(fast=10, slow=30),
        )
        result = engine.run()
        assert len(result["equity_curve"]) > 0

    def test_final_equity_positive(self, sample_df):
        engine = BacktestEngine(
            price_data={"TEST": sample_df},
            strategy=TrendFilterStrategy(period=50),
            initial_capital=50_000,
        )
        result = engine.run()
        metrics = result["metrics"]
        assert metrics["final_equity"] is not None
        assert metrics["final_equity"] > 0

    def test_commission_reduces_returns(self, sample_df):
        no_comm = BacktestEngine(
            price_data={"TEST": sample_df},
            strategy=MACrossoverStrategy(fast=5, slow=20),
            initial_capital=100_000,
            commission_bps=0,
        ).run()
        with_comm = BacktestEngine(
            price_data={"TEST": sample_df},
            strategy=MACrossoverStrategy(fast=5, slow=20),
            initial_capital=100_000,
            commission_bps=50,
        ).run()
        # Higher commission should result in lower or equal final equity
        assert (
            with_comm["metrics"]["final_equity"] <= no_comm["metrics"]["final_equity"]
        )
