from fastapi import APIRouter

from app.api.v1 import instruments, prices, indicators, signals, backtest, portfolio

router = APIRouter(prefix="/api/v1")

router.include_router(instruments.router)
router.include_router(prices.router)
router.include_router(indicators.router)
router.include_router(signals.router)
router.include_router(backtest.router)
router.include_router(portfolio.router)
