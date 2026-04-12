import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.db.candles import load_ohlcv_df
from app.db.upsert import build_upsert
from app.models.signal import Signal
from app.schemas.signal import SignalRunRequest, SignalRead, SignalList, StrategyInfo, StrategyListResponse
from app.services.signals.registry import get_strategy, list_strategies

router = APIRouter(tags=["signals"])


@router.get("/strategies", response_model=StrategyListResponse)
async def list_available_strategies() -> StrategyListResponse:
    return StrategyListResponse(strategies=[StrategyInfo(**s) for s in list_strategies()])


@router.post("/signals/run", status_code=201)
async def run_signals(body: SignalRunRequest, session: SessionDep) -> dict:
    try:
        strategy = get_strategy(body.strategy_name, **body.params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    results: dict[str, list] = {}
    for instrument_id in body.instrument_ids:
        df = await load_ohlcv_df(session, instrument_id, body.date_from, body.date_to)
        if df.empty:
            results[str(instrument_id)] = []
            continue

        signal_series = strategy.generate(df)

        results[str(instrument_id)] = [
            {
                "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "direction": int(v),
            }
            for idx, v in signal_series.items()
        ]

        if body.persist:
            records = [
                {
                    "instrument_id": instrument_id,
                    "date": idx,
                    "strategy_name": body.strategy_name,
                    "params": body.params,
                    "direction": int(v),
                }
                for idx, v in signal_series.items()
            ]
            if records:
                # index_elements must match an existing unique index exactly.
                # The Signal table has UniqueConstraint on all 4 columns.
                # In SQLite, "params" is stored as TEXT — usable in a unique index.
                # In PostgreSQL, the named constraint covers all 4 columns.
                await session.execute(
                    build_upsert(
                        Signal,
                        records,
                        index_elements=["instrument_id", "date", "strategy_name", "params"],
                        constraint_name="uq_signals_instrument_date_strategy_params",
                        update_fields=["direction"],
                    )
                )

    return {"strategy": body.strategy_name, "results": results}


@router.get("/instruments/{instrument_id}/signals", response_model=SignalList)
async def get_signals(
    instrument_id: uuid.UUID,
    session: SessionDep,
    strategy_name: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> SignalList:
    stmt = select(Signal).where(Signal.instrument_id == instrument_id)
    if strategy_name:
        stmt = stmt.where(Signal.strategy_name == strategy_name)
    if from_date:
        stmt = stmt.where(Signal.date >= from_date)
    if to_date:
        stmt = stmt.where(Signal.date <= to_date)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    items = (await session.execute(stmt.order_by(Signal.date).limit(limit).offset(offset))).scalars().all()
    return SignalList(items=list(items), total=total)
