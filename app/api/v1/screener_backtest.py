import math
from datetime import timedelta

from fastapi import APIRouter, HTTPException

from app.core.dependencies import SessionDep
from app.db.candles import load_ohlcv_multi
from app.schemas.backtest import BacktestMetrics, EquityPoint, TradeRecord
from app.schemas.screener_backtest import (
    BenchmarkComparison,
    HoldingSnapshot,
    RebalanceEntry,
    ScreenerRotationRequest,
    ScreenerRotationResult,
)
from app.services.screener.rotation import run_buy_and_hold_benchmark, run_rotation

router = APIRouter(tags=["screener"])
BENCHMARK_TICKER = "SPY"


@router.post("/screener/rotation/run", response_model=ScreenerRotationResult)
async def run_screener_rotation(
    body: ScreenerRotationRequest,
    session: SessionDep,
) -> ScreenerRotationResult:
    """Run a screener-rotation backtest over the given universe and date range.

    Rebalances monthly (first trading day of each calendar month).
    Only assets with label BUY/WATCH and data_quality GOOD/LIMITED receive
    a portfolio weight. If no eligible assets exist on a rebalance date the
    strategy sits in cash until the next rebalance.
    """
    requested_tickers = [t.strip().upper() for t in body.instrument_tickers if t.strip()]
    if not requested_tickers:
        raise HTTPException(status_code=422, detail="instrument_tickers cannot be empty.")

    if body.rebalance_frequency != "monthly":
        raise HTTPException(
            status_code=422,
            detail="Only 'monthly' rebalance_frequency is supported in V1.",
        )

    # Extend load window backwards to cover the warm-up period.
    # Multiply by 1.5 to account for weekends and holidays in the calendar span.
    load_start = body.date_from - timedelta(days=math.ceil(body.warmup_bars * 1.5))

    load_tickers = list(dict.fromkeys([*requested_tickers, BENCHMARK_TICKER]))

    # load_ohlcv_multi raises 404 if any ticker is missing from the instruments table
    all_dfs = await load_ohlcv_multi(session, load_tickers, load_start, body.date_to)
    if not all_dfs:
        raise HTTPException(
            status_code=404,
            detail="No price data found for the requested tickers in the given date range.",
        )

    dfs = {ticker: all_dfs[ticker] for ticker in requested_tickers}
    benchmark_df = all_dfs.get(BENCHMARK_TICKER)
    if benchmark_df is None or benchmark_df[benchmark_df.index >= body.date_from].empty:
        raise HTTPException(
            status_code=404,
            detail="No SPY benchmark price data found for the given date range.",
        )

    result = run_rotation(
        dfs=dfs,
        top_n=body.top_n,
        initial_capital=body.initial_capital,
        commission_bps=body.commission_bps,
        eval_start_date=body.date_from,
    )
    benchmark = run_buy_and_hold_benchmark(
        benchmark_df=benchmark_df,
        initial_capital=body.initial_capital,
        commission_bps=body.commission_bps,
        eval_start_date=body.date_from,
        eval_end_date=body.date_to,
    )

    return ScreenerRotationResult(
        date_from=str(body.date_from),
        date_to=str(body.date_to),
        universe=sorted(dfs.keys()),
        top_n=body.top_n,
        rebalance_frequency=body.rebalance_frequency,
        warmup_bars_requested=body.warmup_bars,
        warmup_bars_available=result["warmup_bars_available"],
        metrics=BacktestMetrics(**result["metrics"]),
        equity_curve=[EquityPoint(**e) for e in result["equity_curve"]],
        rebalance_log=[RebalanceEntry(**r) for r in result["rebalance_log"]],
        holdings_by_rebalance=[HoldingSnapshot(**h) for h in result["holdings_by_rebalance"]],
        trades=[TradeRecord(**t) for t in result["trades"]],
        benchmark=BenchmarkComparison(
            ticker=BENCHMARK_TICKER,
            final_equity=benchmark["metrics"]["final_equity"],
            cagr=benchmark["metrics"]["cagr"],
            max_drawdown=benchmark["metrics"]["max_drawdown"],
            sharpe_ratio=benchmark["metrics"]["sharpe_ratio"],
            equity_curve=[EquityPoint(**e) for e in benchmark["equity_curve"]],
        ),
    )
