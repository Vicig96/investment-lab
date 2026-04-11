import uuid
from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.config import get_settings
from app.core.dependencies import SessionDep
from app.models.price_candle import PriceCandle
from app.models.signal import Signal
from app.schemas.signal import SignalRunRequest, SignalRead, SignalList, StrategyInfo, StrategyListResponse
from app.services.signals.registry import get_strategy, list_strategies


def _build_signal_upsert(records: list[dict]):
    """Dialect-aware INSERT … ON CONFLICT for signals."""
    settings = get_settings()
    if settings.is_sqlite:
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(Signal).values(records)
        return stmt.on_conflict_do_update(
            index_elements=["instrument_id", "date", "strategy_name", "params"],
            set_={"direction": stmt.excluded.direction},
        )
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(Signal).values(records)
        return stmt.on_conflict_do_update(
            constraint="uq_signals_instrument_date_strategy_params",
            set_={"direction": stmt.excluded.direction},
        )

router = APIRouter(tags=["signals"])


async def _load_df(
    session: SessionDep,
    instrument_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
) -> pd.DataFrame:
    stmt = select(PriceCandle).where(PriceCandle.instrument_id == instrument_id)
    if from_date:
        stmt = stmt.where(PriceCandle.date >= from_date)
    if to_date:
        stmt = stmt.where(PriceCandle.date <= to_date)
    stmt = stmt.order_by(PriceCandle.date)
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"date": c.date, "open": float(c.open), "high": float(c.high),
          "low": float(c.low), "close": float(c.close)}
         for c in rows]
    )
    df.set_index("date", inplace=True)
    return df


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
        df = await _load_df(session, instrument_id, body.date_from, body.date_to)
        if df.empty:
            results[str(instrument_id)] = []
            continue

        signal_series = strategy.generate(df)

        signal_rows = [
            {
                "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                "direction": int(v),
            }
            for idx, v in signal_series.items()
        ]
        results[str(instrument_id)] = signal_rows

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
                await session.execute(_build_signal_upsert(records))

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
