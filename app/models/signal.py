import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, SmallInteger, Numeric, BigInteger, ForeignKey, UniqueConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID, JSONBCompat


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "date", "strategy_name", "params",
            name="uq_signals_instrument_date_strategy_params"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    params: Mapped[dict] = mapped_column(JSONBCompat(), nullable=False, default=dict)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    strength: Mapped[float | None] = mapped_column(Numeric(6, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="signals")  # noqa: F821
