import uuid
from datetime import date

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.core.dependencies import SessionDep
from app.db.candles import load_ohlcv_df
from app.schemas.indicator import IndicatorResponse, IndicatorDataPoint, IndicatorListResponse, IndicatorInfo
from app.services.indicators.registry import get_indicator, list_indicators

router = APIRouter(tags=["indicators"])


@router.get("/indicators", response_model=IndicatorListResponse)
async def list_available_indicators() -> IndicatorListResponse:
    return IndicatorListResponse(
        indicators=[IndicatorInfo(**i) for i in list_indicators()]
    )


@router.get(
    "/instruments/{instrument_id}/indicators/{indicator_name}",
    response_model=IndicatorResponse,
)
async def compute_indicator(
    instrument_id: uuid.UUID,
    indicator_name: str,
    session: SessionDep,
    from_date: date | None = None,
    to_date: date | None = None,
    period: int | None = None,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    trading_days: int | None = None,
) -> IndicatorResponse:
    try:
        params: dict = {}
        if period is not None:
            params["period"] = period
        if fast is not None:
            params["fast"] = fast
        if slow is not None:
            params["slow"] = slow
        if signal is not None:
            params["signal"] = signal
        if trading_days is not None:
            params["trading_days"] = trading_days

        indicator = get_indicator(indicator_name, **params)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    df = await load_ohlcv_df(session, instrument_id, from_date, to_date)
    if df.empty:
        raise HTTPException(status_code=404, detail="No price data found for this instrument.")

    series = indicator.compute(df)

    data = [
        IndicatorDataPoint(date=idx, value=(None if pd.isna(v) else float(v)))
        for idx, v in series.items()
    ]

    return IndicatorResponse(
        instrument_id=instrument_id,
        indicator_name=indicator_name,
        params=indicator.param_fingerprint(),
        data=data,
    )
