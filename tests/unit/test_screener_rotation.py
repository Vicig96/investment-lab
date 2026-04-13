"""Deterministic tests for the Screener Rotation engine."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.services.screener import rotation as rotation_module
from app.services.screener.rotation import run_buy_and_hold_benchmark, run_rotation


def _df(rows: list[tuple[date, float]]) -> pd.DataFrame:
    data = []
    for current_date, close in rows:
        data.append({
            "date": current_date,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000,
        })
    df = pd.DataFrame(data)
    return df.set_index("date").sort_index()


def _patch_ranked(monkeypatch: pytest.MonkeyPatch, ranked_rows: list[dict]) -> None:
    def _stub_score_universe(dfs: dict[str, pd.DataFrame], top_n: int) -> tuple[date, list[dict]]:
        snapshot_date = max(df.index[-1] for df in dfs.values())
        return snapshot_date, ranked_rows

    monkeypatch.setattr(rotation_module, "score_universe", _stub_score_universe)


def test_rotation_always_cash_keeps_equity_flat(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ranked(monkeypatch, [
        {"ticker": "SPY", "label": "AVOID", "data_quality": "GOOD", "suggested_weight": None},
    ])

    dfs = {
        "SPY": _df([
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 3), 101.0),
            (date(2024, 2, 1), 102.0),
        ]),
    }

    result = run_rotation(
        dfs=dfs,
        top_n=1,
        initial_capital=1_000,
        commission_bps=10,
        eval_start_date=date(2024, 1, 2),
        defensive_mode="cash",
    )

    assert result["trades"] == []
    assert [point["equity"] for point in result["equity_curve"]] == [1000.0, 1000.0, 1000.0]
    assert result["metrics"]["final_equity"] == 1000.0
    assert result["metrics"]["max_drawdown"] == 0.0


def test_rotation_buy_sizing_reserves_commission(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ranked(monkeypatch, [
        {"ticker": "SPY", "label": "BUY", "data_quality": "GOOD", "suggested_weight": 1.0},
    ])

    dfs = {
        "SPY": _df([
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 3), 100.0),
        ]),
    }

    result = run_rotation(
        dfs=dfs,
        top_n=1,
        initial_capital=1_000,
        commission_bps=100,
        eval_start_date=date(2024, 1, 2),
    )

    buy_trade = next(trade for trade in result["trades"] if trade["action"] == "buy")
    buy_notional = buy_trade["shares"] * buy_trade["price"]

    assert buy_notional + buy_trade["commission"] == pytest.approx(1_000.0, abs=1e-3)
    assert result["metrics"]["final_equity"] == pytest.approx(990.1, abs=1e-2)
    assert result["metrics"]["max_drawdown"] == 0.0


def test_rotation_uses_last_known_price_when_asset_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ranked(monkeypatch, [
        {"ticker": "SPY", "label": "BUY", "data_quality": "GOOD", "suggested_weight": 1.0},
        {"ticker": "QQQ", "label": "AVOID", "data_quality": "GOOD", "suggested_weight": None},
    ])

    dfs = {
        "SPY": _df([
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 4), 100.0),
        ]),
        "QQQ": _df([
            (date(2024, 1, 2), 50.0),
            (date(2024, 1, 3), 50.0),
            (date(2024, 1, 4), 50.0),
        ]),
    }

    result = run_rotation(
        dfs=dfs,
        top_n=1,
        initial_capital=1_000,
        commission_bps=0,
        eval_start_date=date(2024, 1, 2),
    )

    assert [point["equity"] for point in result["equity_curve"]] == [1000.0, 1000.0, 1000.0]
    assert result["metrics"]["max_drawdown"] == 0.0


def test_rotation_one_asset_rebalance_remains_fully_funded(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ranked(monkeypatch, [
        {"ticker": "SPY", "label": "BUY", "data_quality": "GOOD", "suggested_weight": 1.0},
    ])

    dfs = {
        "SPY": _df([
            (date(2024, 1, 2), 100.0),
            (date(2024, 1, 31), 120.0),
            (date(2024, 2, 1), 120.0),
            (date(2024, 2, 2), 120.0),
        ]),
    }

    result = run_rotation(
        dfs=dfs,
        top_n=1,
        initial_capital=1_000,
        commission_bps=0,
        eval_start_date=date(2024, 1, 2),
    )

    assert [point["equity"] for point in result["equity_curve"]] == [1000.0, 1200.0, 1200.0, 1200.0]
    assert result["metrics"]["final_equity"] == 1200.0
    assert result["metrics"]["max_drawdown"] == 0.0
    assert result["metrics"]["total_trades"] == 1


def test_benchmark_buy_and_hold_metrics_follow_curve() -> None:
    benchmark_df = _df([
        (date(2024, 1, 2), 100.0),
        (date(2024, 1, 3), 120.0),
        (date(2024, 1, 4), 90.0),
    ])

    result = run_buy_and_hold_benchmark(
        benchmark_df=benchmark_df,
        initial_capital=1_000,
        commission_bps=0,
        eval_start_date=date(2024, 1, 2),
        eval_end_date=date(2024, 1, 4),
    )

    assert [point["equity"] for point in result["equity_curve"]] == [1000.0, 1200.0, 900.0]
    assert result["metrics"]["final_equity"] == 900.0
    assert result["metrics"]["max_drawdown"] == pytest.approx(-0.25, abs=1e-9)
