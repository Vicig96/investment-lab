import uuid
from decimal import Decimal

from sqlalchemy import Numeric, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID, JSONBCompat


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("backtest_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    cagr: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    calmar_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    total_trades: Mapped[int | None] = mapped_column(Integer)
    final_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    equity_curve: Mapped[list] = mapped_column(JSONBCompat(), default=list)
    trades: Mapped[list] = mapped_column(JSONBCompat(), default=list)

    run: Mapped["BacktestRun"] = relationship("BacktestRun", back_populates="result")  # noqa: F821
