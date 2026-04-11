"""Tests for risk functions."""
import pytest

from app.services.risk.position_sizing import fixed_fractional_size, kelly_fraction
from app.services.risk.stop_loss import percentage_stop, atr_stop, stop_distance
from app.services.risk.portfolio_exposure import (
    max_position_weight,
    max_open_positions,
    portfolio_heat,
    compute_sector_exposure,
)


class TestPositionSizing:
    def test_fixed_fractional_basic(self):
        shares = fixed_fractional_size(capital=10_000, price=100, risk_per_trade=0.01)
        assert shares == 1  # 10000 * 0.01 / 100 = 1

    def test_fixed_fractional_with_stop(self):
        shares = fixed_fractional_size(
            capital=100_000, price=100, risk_per_trade=0.01, stop_distance=5.0
        )
        # 100000 * 0.01 / 5 = 200
        assert shares == 200

    def test_zero_price_returns_zero(self):
        assert fixed_fractional_size(100_000, 0) == 0

    def test_kelly_typical(self):
        k = kelly_fraction(win_rate=0.6, avg_win=0.05, avg_loss=0.03)
        assert 0 < k < 1

    def test_kelly_negative_clamped(self):
        # Win rate too low should return 0
        k = kelly_fraction(win_rate=0.1, avg_win=0.01, avg_loss=0.10)
        assert k == 0.0


class TestStopLoss:
    def test_percentage_stop(self):
        stop = percentage_stop(entry_price=100, stop_pct=0.02)
        assert abs(stop - 98.0) < 1e-9

    def test_atr_stop(self):
        stop = atr_stop(entry_price=100, atr=2.0, multiplier=2.0)
        assert abs(stop - 96.0) < 1e-9

    def test_stop_distance(self):
        d = stop_distance(100, 95)
        assert abs(d - 5.0) < 1e-9


class TestPortfolioExposure:
    def test_max_weight_within(self):
        assert max_position_weight(1_000, 20_000, max_weight=0.10) is True

    def test_max_weight_exceeded(self):
        assert max_position_weight(3_000, 20_000, max_weight=0.10) is False

    def test_max_open_positions_within(self):
        assert max_open_positions(5, 10) is True

    def test_max_open_positions_at_limit(self):
        assert max_open_positions(10, 10) is False

    def test_portfolio_heat_within(self):
        assert portfolio_heat([0.01, 0.01, 0.01], max_heat=0.06) is True

    def test_portfolio_heat_exceeded(self):
        assert portfolio_heat([0.02, 0.02, 0.02, 0.02], max_heat=0.06) is False

    def test_sector_exposure(self):
        positions = [
            {"ticker": "AAPL", "weight": 0.10, "sector": "tech"},
            {"ticker": "MSFT", "weight": 0.08, "sector": "tech"},
            {"ticker": "JPM", "weight": 0.05, "sector": "finance"},
        ]
        exposure = compute_sector_exposure(positions)
        assert abs(exposure["tech"] - 0.18) < 1e-9
        assert abs(exposure["finance"] - 0.05) < 1e-9
