from fastapi import APIRouter, HTTPException

from app.core.dependencies import SessionDep
from app.db.candles import load_ohlcv_multi
from app.schemas.screener import RankedAsset, ScreenerRequest, ScreenerResponse
from app.services.screener.scorer import score_universe

router = APIRouter(tags=["screener"])


@router.post("/screener/run", response_model=ScreenerResponse)
async def run_screener(body: ScreenerRequest, session: SessionDep) -> ScreenerResponse:
    """Rank a universe of instruments by trend, momentum, and risk.

    Scores each asset cross-sectionally, labels it BUY / WATCH / AVOID,
    and assigns inverse-volatility portfolio weights to the top_n eligible assets.
    """
    tickers = [t.strip().upper() for t in body.instrument_tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=422, detail="instrument_tickers cannot be empty.")

    # load_ohlcv_multi raises 404 if any ticker is not found in instruments table
    dfs = await load_ohlcv_multi(session, tickers, body.date_from, body.date_to)
    if not dfs:
        raise HTTPException(
            status_code=404,
            detail="No price data found for any of the requested tickers in the given date range.",
        )

    snapshot_date, ranked = score_universe(dfs, top_n=body.top_n)

    return ScreenerResponse(
        snapshot_date=snapshot_date,
        universe_size=len(ranked),
        ranked_assets=[RankedAsset(**r) for r in ranked],
    )
