import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    asset_class: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    candles: Mapped[list["PriceCandle"]] = relationship(  # noqa: F821
        "PriceCandle", back_populates="instrument", cascade="all, delete-orphan"
    )
    indicator_caches: Mapped[list["IndicatorCache"]] = relationship(  # noqa: F821
        "IndicatorCache", back_populates="instrument", cascade="all, delete-orphan"
    )
    signals: Mapped[list["Signal"]] = relationship(  # noqa: F821
        "Signal", back_populates="instrument", cascade="all, delete-orphan"
    )
