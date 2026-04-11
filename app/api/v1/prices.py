import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.models.instrument import Instrument
from app.models.price_candle import PriceCandle
from app.schemas.price_candle import PriceCandleRead, CandleList, PriceSummary
from app.services.data_ingestion.ingestor import ingest_csv

router = APIRouter(tags=["prices"])


@router.post("/prices/ingest", status_code=201)
async def ingest_prices(
    session: SessionDep,
    instrument_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="Only CSV files are accepted.")

    content = await file.read()
    try:
        count = await ingest_csv(session, instrument_id, content)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"rows_upserted": count, "instrument_id": str(instrument_id)}


@router.get("/instruments/{instrument_id}/prices", response_model=CandleList)
async def list_prices(
    instrument_id: uuid.UUID,
    session: SessionDep,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> CandleList:
    stmt = select(PriceCandle).where(PriceCandle.instrument_id == instrument_id)
    if from_date:
        stmt = stmt.where(PriceCandle.date >= from_date)
    if to_date:
        stmt = stmt.where(PriceCandle.date <= to_date)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(PriceCandle.date).limit(limit).offset(offset)
    items = (await session.execute(stmt)).scalars().all()
    return CandleList(items=list(items), total=total)


@router.get("/instruments/{instrument_id}/prices/summary", response_model=PriceSummary)
async def price_summary(instrument_id: uuid.UUID, session: SessionDep) -> PriceSummary:
    result = await session.execute(select(Instrument).where(Instrument.id == instrument_id))
    instrument = result.scalar_one_or_none()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found.")

    agg = await session.execute(
        select(
            func.count(PriceCandle.id),
            func.min(PriceCandle.date),
            func.max(PriceCandle.date),
        ).where(PriceCandle.instrument_id == instrument_id)
    )
    count, min_date, max_date = agg.one()

    last_close = None
    if max_date:
        last_row = await session.execute(
            select(PriceCandle.close)
            .where(PriceCandle.instrument_id == instrument_id)
            .where(PriceCandle.date == max_date)
        )
        last_close = last_row.scalar_one_or_none()

    return PriceSummary(
        instrument_id=instrument_id,
        ticker=instrument.ticker,
        total_candles=count,
        date_from=min_date,
        date_to=max_date,
        last_close=last_close,
    )
