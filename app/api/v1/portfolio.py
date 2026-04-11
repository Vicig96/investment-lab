from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.models.instrument import Instrument
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.price_candle import PriceCandle
from app.schemas.portfolio import (
    PortfolioSimRequest,
    PortfolioSnapshotRead,
    PortfolioSnapshotList,
    RebalanceResponse,
    RebalanceOrder,
)
from app.services.portfolio.rebalancer import compute_rebalance_orders
from app.services.portfolio.simulator import simulate_portfolio
from app.services.signals.registry import get_strategy

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _load_prices(
    session: SessionDep, tickers: list[str], date_from: date, date_to: date
) -> dict[str, pd.DataFrame]:
    price_data: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        inst = (
            await session.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        ).scalar_one_or_none()
        if inst is None:
            raise HTTPException(status_code=404, detail=f"Instrument '{ticker}' not found.")

        rows = (
            await session.execute(
                select(PriceCandle)
                .where(PriceCandle.instrument_id == inst.id)
                .where(PriceCandle.date >= date_from)
                .where(PriceCandle.date <= date_to)
                .order_by(PriceCandle.date)
            )
        ).scalars().all()

        if rows:
            df = pd.DataFrame(
                [{"date": c.date, "open": float(c.open), "high": float(c.high),
                  "low": float(c.low), "close": float(c.close)}
                 for c in rows]
            )
            df.set_index("date", inplace=True)
            price_data[ticker.upper()] = df
    return price_data


@router.post("/simulate", status_code=201)
async def simulate(body: PortfolioSimRequest, session: SessionDep) -> dict:
    try:
        strategy = get_strategy(body.strategy_name, **body.params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    price_data = await _load_prices(
        session, body.instrument_tickers, body.date_from, body.date_to
    )
    if not price_data:
        raise HTTPException(status_code=404, detail="No price data found for the given instruments and range.")

    result = simulate_portfolio(
        price_data=price_data,
        strategy=strategy,
        initial_capital=float(body.initial_capital),
        date_from=body.date_from,
        date_to=body.date_to,
    )
    return result


@router.get("/snapshot", response_model=PortfolioSnapshotRead | None)
async def latest_snapshot(session: SessionDep) -> PortfolioSnapshotRead | None:
    result = await session.execute(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date.desc()).limit(1)
    )
    snap = result.scalar_one_or_none()
    if not snap:
        return None
    return PortfolioSnapshotRead.model_validate(snap)


@router.get("/snapshots", response_model=PortfolioSnapshotList)
async def list_snapshots(
    session: SessionDep,
    limit: int = 30,
    offset: int = 0,
) -> PortfolioSnapshotList:
    total = (await session.execute(select(func.count(PortfolioSnapshot.id)))).scalar_one()
    items = (
        await session.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return PortfolioSnapshotList(items=list(items), total=total)


@router.post("/rebalance", response_model=RebalanceResponse)
async def rebalance(
    session: SessionDep,
    target_weights: dict[str, float],
    nav: float,
    current_positions: list[dict] | None = None,
) -> RebalanceResponse:
    if current_positions is None:
        current_positions = []

    tickers = list(target_weights.keys())
    latest_prices: dict[str, float] = {}
    for ticker in tickers:
        inst = (
            await session.execute(select(Instrument).where(Instrument.ticker == ticker.upper()))
        ).scalar_one_or_none()
        if inst:
            row = (
                await session.execute(
                    select(PriceCandle.close)
                    .where(PriceCandle.instrument_id == inst.id)
                    .order_by(PriceCandle.date.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row:
                latest_prices[ticker.upper()] = float(row)

    orders = compute_rebalance_orders(
        current_positions=current_positions,
        target_weights=target_weights,
        nav=nav,
        prices=latest_prices,
    )

    return RebalanceResponse(
        snapshot_date=date.today(),
        nav=nav,
        orders=[
            RebalanceOrder(
                ticker=o.ticker,
                action=o.action,
                current_weight=o.current_weight,
                target_weight=o.target_weight,
                delta_weight=o.delta_weight,
                estimated_shares=o.estimated_shares,
                estimated_value=o.estimated_value,
            )
            for o in orders
        ],
    )
