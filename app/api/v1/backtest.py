import uuid
from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.core.logging import get_logger
from app.models.backtest_result import BacktestResult
from app.models.backtest_run import BacktestRun
from app.models.instrument import Instrument
from app.models.price_candle import PriceCandle
from app.schemas.backtest import (
    BacktestRequest,
    BacktestRunRead,
    BacktestResultRead,
    BacktestList,
    EquityPoint,
    TradeRecord,
)
from app.services.backtest.engine import BacktestEngine
from app.services.signals.registry import get_strategy

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = get_logger(__name__)


async def _load_price_data(
    session: SessionDep,
    tickers: list[str],
    date_from,
    date_to,
) -> dict[str, pd.DataFrame]:
    price_data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        inst_result = await session.execute(
            select(Instrument).where(Instrument.ticker == ticker.upper())
        )
        instrument = inst_result.scalar_one_or_none()
        if instrument is None:
            raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found.")

        stmt = (
            select(PriceCandle)
            .where(PriceCandle.instrument_id == instrument.id)
            .where(PriceCandle.date >= date_from)
            .where(PriceCandle.date <= date_to)
            .order_by(PriceCandle.date)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            continue

        df = pd.DataFrame(
            [{"date": c.date, "open": float(c.open), "high": float(c.high),
              "low": float(c.low), "close": float(c.close)}
             for c in rows]
        )
        df.set_index("date", inplace=True)
        price_data[ticker.upper()] = df

    return price_data


@router.post("/run", status_code=201)
async def run_backtest(body: BacktestRequest, session: SessionDep) -> dict:
    try:
        strategy = get_strategy(body.strategy_name, **body.params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    run = BacktestRun(
        strategy_name=body.strategy_name,
        instruments=body.instrument_tickers,
        params=body.params,
        date_from=body.date_from,
        date_to=body.date_to,
        initial_capital=body.initial_capital,
        commission_bps=body.commission_bps,
        status="running",
    )
    session.add(run)
    await session.flush()

    try:
        price_data = await _load_price_data(
            session, body.instrument_tickers, body.date_from, body.date_to
        )
        if not price_data:
            raise ValueError("No price data found for the specified instruments and date range.")

        engine = BacktestEngine(
            price_data=price_data,
            strategy=strategy,
            initial_capital=float(body.initial_capital),
            commission_bps=float(body.commission_bps),
            date_from=body.date_from,
            date_to=body.date_to,
        )
        result_data = engine.run()
        metrics = result_data["metrics"]

        bt_result = BacktestResult(
            run_id=run.id,
            cagr=metrics.get("cagr"),
            max_drawdown=metrics.get("max_drawdown"),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            calmar_ratio=metrics.get("calmar_ratio"),
            win_rate=metrics.get("win_rate"),
            total_trades=metrics.get("total_trades"),
            final_equity=metrics.get("final_equity"),
            equity_curve=result_data["equity_curve"],
            trades=result_data["trades"],
        )
        session.add(bt_result)

        run.status = "complete"
        run.completed_at = datetime.now(timezone.utc)

    except Exception as exc:
        run.status = "error"
        run.error_message = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        logger.error("backtest_failed", run_id=str(run.id), error=str(exc))
        await session.flush()
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")

    await session.flush()
    return {"run_id": str(run.id), "status": run.status}


@router.get("", response_model=BacktestList)
async def list_backtests(
    session: SessionDep,
    limit: int = 20,
    offset: int = 0,
) -> BacktestList:
    total = (await session.execute(select(func.count(BacktestRun.id)))).scalar_one()
    items = (
        await session.execute(
            select(BacktestRun).order_by(BacktestRun.started_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return BacktestList(items=list(items), total=total)


@router.get("/{run_id}", response_model=BacktestRunRead)
async def get_backtest_run(run_id: uuid.UUID, session: SessionDep) -> BacktestRunRead:
    result = await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found.")
    return BacktestRunRead.model_validate(run)


@router.get("/{run_id}/results", response_model=BacktestResultRead)
async def get_backtest_results(run_id: uuid.UUID, session: SessionDep) -> BacktestResultRead:
    result = await session.execute(
        select(BacktestResult).where(BacktestResult.run_id == run_id)
    )
    bt_result = result.scalar_one_or_none()
    if not bt_result:
        raise HTTPException(status_code=404, detail="Backtest result not found.")
    return BacktestResultRead.model_validate(bt_result)
