import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, BigInteger, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID


class PriceCandle(Base):
    __tablename__ = "price_candles"
    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_price_candles_instrument_id_date"),
        Index("ix_price_candles_instrument_date", "instrument_id", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)

    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="candles")  # noqa: F821
