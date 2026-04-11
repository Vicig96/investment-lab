from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(log_level=settings.log_level, production=settings.is_production)

    # Auto-create tables for SQLite (local dev) — no Alembic needed.
    # For PostgreSQL, run: alembic upgrade head
    if settings.is_sqlite:
        from app.db.init_db import create_tables
        await create_tables()
        logger.info("sqlite_dev_mode", db=settings.database_url)
    else:
        logger.info("postgresql_mode", hint="run 'alembic upgrade head' if needed")

    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Investment Lab",
        description=(
            "Private investment analysis tool: indicators, signals, backtesting, "
            "and portfolio simulation. NO real order execution."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(v1_router)

    return app


app = create_app()
