"""Upsert parsed OHLCV rows into the database."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.instrument import Instrument
from app.models.price_candle import PriceCandle
from app.services.data_ingestion.csv_loader import parse_ohlcv_csv

logger = get_logger(__name__)


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
    instrument = result.scalar_one_or_none()
    if instrument is None:
        raise ValueError(f"Instrument {instrument_id} not found.")

    rows = parse_ohlcv_csv(source)
    if not rows:
        return 0

    records = [
        {
            "instrument_id": instrument_id,
            "date": row["date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "adj_close": row.get("adj_close"),
            "volume": row.get("volume"),
        }
        for row in rows
    ]

    stmt = pg_insert(PriceCandle).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_price_candles_instrument_id_date",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)

    logger.info("csv_ingested", instrument_id=str(instrument_id), rows=len(records))
    return len(records)
