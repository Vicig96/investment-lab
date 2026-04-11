import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    instruments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    commission_bps: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("10"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    result: Mapped["BacktestResult | None"] = relationship(  # noqa: F821
        "BacktestResult", back_populates="run", uselist=False, cascade="all, delete-orphan"
    )
