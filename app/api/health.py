from fastapi import APIRouter
from sqlalchemy import text

from app.core.dependencies import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/readiness")
async def readiness(session: SessionDep) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "db": "connected"}
