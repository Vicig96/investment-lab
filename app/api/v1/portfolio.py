from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.db.candles import load_ohlcv_multi
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


@router.post("/simulate", status_code=201)
async def simulate(body: PortfolioSimRequest, session: SessionDep) -> dict:
    try:
        strategy = get_strategy(body.strategy_name, **body.params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # load_ohlcv_multi resolves all tickers in 2 queries (no N+1)
    price_data = await load_ohlcv_multi(
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

    # Batch fetch instruments + their latest price in 2 queries
    insts = (
        await session.execute(
            select(Instrument).where(Instrument.ticker.in_([t.upper() for t in tickers]))
        )
    ).scalars().all()

    for inst in insts:
        row = (
            await session.execute(
                select(PriceCandle.close)
                .where(PriceCandle.instrument_id == inst.id)
                .order_by(PriceCandle.date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row:
            latest_prices[inst.ticker] = float(row)

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
