import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, BigInteger, ForeignKey, UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class IndicatorCache(Base):
    __tablename__ = "indicator_cache"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "date", "indicator_name", "params",
            name="uq_indicator_cache_instrument_date_name_params"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    instrument: Mapped["Instrument"] = relationship("Instrument", back_populates="indicator_caches")  # noqa: F821
