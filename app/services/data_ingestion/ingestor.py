"""Upsert parsed OHLCV rows into the database."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.upsert import build_upsert
from app.models.instrument import Instrument
from app.models.price_candle import PriceCandle
from app.services.data_ingestion.csv_loader import parse_ohlcv_csv

logger = get_logger(__name__)

_PRICE_CANDLE_UPDATE_FIELDS = ["open", "high", "low", "close", "adj_close", "volume"]


async def ingest_csv(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    source: Any,
) -> int:
    """Parse a CSV source and upsert candles for the given instrument.

    Returns:
        Number of rows upserted.

    Raises:
        ValueError: If the instrument does not exist or the CSV is invalid.
    """
    result = await session.execute(select(Instrument).where(Instrument.id == instrument_id))
    if result.scalar_one_or_none() is None:
        raise ValueError(f"Instrument {instrument_id} not found.")

    rows = parse_ohlcv_csv(source)
    if not rows:
        return 0

    # Get next available id for this batch (SQLite autoincrement workaround)
    max_id_result = await session.execute(select(func.max(PriceCandle.id)))
    max_id = max_id_result.scalar_one_or_none() or 0

    records = [
        {
            "id": max_id + i + 1,
            "instrument_id": instrument_id,
            "date": row["date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "adj_close": row.get("adj_close"),
            "volume": row.get("volume"),
        }
        for i, row in enumerate(rows)
    ]

    stmt = build_upsert(
        PriceCandle,
        records,
        index_elements=["instrument_id", "date"],
        constraint_name="uq_price_candles_instrument_id_date",
        update_fields=_PRICE_CANDLE_UPDATE_FIELDS,
    )
    await session.execute(stmt)
    await session.flush()  # Force type processors and physical write to SQLite

    logger.info("csv_ingested", instrument_id=str(instrument_id), rows=len(records))
    return len(records)
