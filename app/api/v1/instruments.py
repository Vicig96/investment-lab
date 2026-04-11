import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.dependencies import SessionDep
from app.models.instrument import Instrument
from app.schemas.instrument import InstrumentCreate, InstrumentRead, InstrumentList

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=InstrumentList)
async def list_instruments(
    session: SessionDep,
    limit: int = 100,
    offset: int = 0,
) -> InstrumentList:
    total_result = await session.execute(select(func.count(Instrument.id)))
    total = total_result.scalar_one()

    result = await session.execute(
        select(Instrument).order_by(Instrument.ticker).limit(limit).offset(offset)
    )
    items = result.scalars().all()
    return InstrumentList(items=list(items), total=total)


@router.post("", response_model=InstrumentRead, status_code=201)
async def create_instrument(body: InstrumentCreate, session: SessionDep) -> InstrumentRead:
    existing = await session.execute(
        select(Instrument).where(Instrument.ticker == body.ticker)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Instrument '{body.ticker}' already exists.")

    instrument = Instrument(**body.model_dump())
    session.add(instrument)
    await session.flush()
    await session.refresh(instrument)
    return InstrumentRead.model_validate(instrument)


@router.get("/{instrument_id}", response_model=InstrumentRead)
async def get_instrument(instrument_id: uuid.UUID, session: SessionDep) -> InstrumentRead:
    result = await session.execute(select(Instrument).where(Instrument.id == instrument_id))
    instrument = result.scalar_one_or_none()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    return InstrumentRead.model_validate(instrument)


@router.delete("/{instrument_id}", status_code=204)
async def delete_instrument(instrument_id: uuid.UUID, session: SessionDep) -> None:
    result = await session.execute(select(Instrument).where(Instrument.id == instrument_id))
    instrument = result.scalar_one_or_none()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found.")
    await session.delete(instrument)
