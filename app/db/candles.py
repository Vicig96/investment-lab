"""Shared helpers for loading OHLCV data into pandas DataFrames.

Centralises the pattern that was duplicated across indicators.py,
signals.py, backtest.py, and portfolio.py.
"""
from __future__ import annotations

import uuid
from datetime import date

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.instrument import Instrument
from app.models.price_candle import PriceCandle


async def load_ohlcv_df(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
) -> pd.DataFrame:
    """Load OHLCV candles for a single instrument as a DataFrame (date index).

    Returns an empty DataFrame when no rows exist for the given filters.
    """
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
        [
            {
                "date": c.date,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
            }
            for c in rows
        ]
    )
    df.set_index("date", inplace=True)
    return df


async def load_ohlcv_multi(
    session: AsyncSession,
    tickers: list[str],
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for multiple tickers using exactly 2 DB queries.

    Args:
        session:   Async SQLAlchemy session.
        tickers:   List of ticker symbols (case-insensitive).
        from_date: Optional start date filter.
        to_date:   Optional end date filter.

    Returns:
        Dict mapping UPPER-CASE ticker → DataFrame (date index).
        Tickers with no data are omitted from the result.

    Raises:
        HTTPException 404 if any ticker is not found in the instruments table.
    """
    upper_tickers = [t.upper() for t in tickers]

    # Query 1: all instruments in one round-trip
    insts = (
        await session.execute(
            select(Instrument).where(Instrument.ticker.in_(upper_tickers))
        )
    ).scalars().all()

    found = {i.ticker for i in insts}
    missing = [t for t in upper_tickers if t not in found]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument(s) not found: {', '.join(missing)}",
        )

    id_to_ticker = {i.id: i.ticker for i in insts}

    # Query 2: all candles for all instruments in one round-trip
    stmt = select(PriceCandle).where(
        PriceCandle.instrument_id.in_(list(id_to_ticker))
    )
    if from_date:
        stmt = stmt.where(PriceCandle.date >= from_date)
    if to_date:
        stmt = stmt.where(PriceCandle.date <= to_date)
    stmt = stmt.order_by(PriceCandle.date)

    all_rows = (await session.execute(stmt)).scalars().all()

    # Group rows by ticker
    buckets: dict[str, list[dict]] = {t: [] for t in upper_tickers}
    for c in all_rows:
        ticker = id_to_ticker.get(c.instrument_id)
        if ticker:
            buckets[ticker].append(
                {
                    "date": c.date,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                }
            )

    result: dict[str, pd.DataFrame] = {}
    for ticker, rows in buckets.items():
        if rows:
            df = pd.DataFrame(rows)
            df.set_index("date", inplace=True)
            result[ticker] = df

    return result
