"""Tests for backtest metrics."""
import pytest

from app.services.backtest.metrics import (
    cagr,
    max_drawdown,
    sharpe_ratio,
    calmar_ratio,
    win_rate,
    compute_all_metrics,
)


def _equity_curve(values: list[float]) -> list[dict]:
    return [{"date": f"2023-01-{i+1:02d}", "equity": v} for i, v in enumerate(values)]


class TestCAGR:
    def test_positive_growth(self):
        # 252 trading days, doubles → CAGR ≈ 100%
        curve = _equity_curve([100_000] + [200_000] * 251)
        result = cagr(curve)
        assert result is not None and result > 0

    def test_insufficient_data_returns_none(self):
        assert cagr([]) is None
        assert cagr(_equity_curve([100_000])) is None

    def test_flat_cagr_near_zero(self):
        curve = _equity_curve([100_000] * 252)
        result = cagr(curve)
        assert result is not None
        assert abs(result) < 0.001


class TestMaxDrawdown:
    def test_no_drawdown(self):
        curve = _equity_curve([100, 110, 120, 130])
        assert max_drawdown(curve) == 0.0

    def test_fifty_pct_drawdown(self):
        curve = _equity_curve([100, 200, 100])
        result = max_drawdown(curve)
        assert abs(result - (-0.5)) < 1e-9

    def test_empty_returns_none(self):
        assert max_drawdown([]) is None


class TestSharpeRatio:
    def test_positive_sharpe(self):
        # Steadily rising equity
        curve = _equity_curve([100 + i for i in range(252)])
        result = sharpe_ratio(curve)
        assert result is not None and result > 0

    def test_insufficient_data(self):
        assert sharpe_ratio(_equity_curve([100_000])) is None


class TestWinRate:
    def test_all_wins(self):
        trades = [{"action": "sell", "pnl": 100}, {"action": "sell", "pnl": 50}]
        assert win_rate(trades) == 1.0

    def test_half_wins(self):
        trades = [
            {"action": "sell", "pnl": 100},
            {"action": "sell", "pnl": -50},
        ]
        assert win_rate(trades) == 0.5

    def test_no_closed_trades_returns_none(self):
        assert win_rate([]) is None

    def test_buy_trades_excluded(self):
        trades = [{"action": "buy", "pnl": None}, {"action": "sell", "pnl": 100}]
        assert win_rate(trades) == 1.0


class TestComputeAllMetrics:
    def test_returns_all_keys(self):
        curve = _equity_curve([100_000 + i * 100 for i in range(252)])
        trades = [{"action": "sell", "pnl": 100}, {"action": "sell", "pnl": -50}]
        result = compute_all_metrics(curve, trades)
        for key in ["cagr", "max_drawdown", "sharpe_ratio", "calmar_ratio", "win_rate", "total_trades", "final_equity"]:
            assert key in result
