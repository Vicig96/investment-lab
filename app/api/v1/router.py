from fastapi import APIRouter

from app.api.v1 import instruments, prices, indicators, signals, backtest, portfolio, screener, screener_backtest

router = APIRouter(prefix="/api/v1")

router.include_router(instruments.router)
router.include_router(prices.router)
router.include_router(indicators.router)
router.include_router(signals.router)
router.include_router(backtest.router)
router.include_router(portfolio.router)
router.include_router(screener.router)
router.include_router(screener_backtest.router)
