"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("asset_class", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        sa.UniqueConstraint("ticker", name="uq_instruments_ticker"),
    )
    op.create_index("ix_instruments_ticker", "instruments", ["ticker"])

    op.create_table(
        "price_candles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("adj_close", sa.Numeric(18, 6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name="fk_price_candles_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_price_candles"),
        sa.UniqueConstraint("instrument_id", "date", name="uq_price_candles_instrument_id_date"),
    )
    op.create_index("ix_price_candles_instrument_date", "price_candles", ["instrument_id", "date"])

    op.create_table(
        "indicator_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("indicator_name", sa.String(50), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("value", sa.Numeric(18, 6), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name="fk_indicator_cache_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_indicator_cache"),
        sa.UniqueConstraint(
            "instrument_id", "date", "indicator_name", "params",
            name="uq_indicator_cache_instrument_date_name_params",
        ),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("direction", sa.SmallInteger(), nullable=False),
        sa.Column("strength", sa.Numeric(6, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name="fk_signals_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signals"),
        sa.UniqueConstraint(
            "instrument_id", "date", "strategy_name", "params",
            name="uq_signals_instrument_date_strategy_params",
        ),
    )

    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_name", sa.String(100), nullable=False),
        sa.Column("instruments", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("initial_capital", sa.Numeric(18, 2), nullable=False),
        sa.Column("commission_bps", sa.Numeric(6, 2), nullable=False, server_default="10"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
    )

    op.create_table(
        "backtest_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cagr", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(8, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("calmar_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("win_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=True),
        sa.Column("final_equity", sa.Numeric(18, 2), nullable=True),
        sa.Column("equity_curve", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("trades", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["backtest_runs.id"],
            name="fk_backtest_results_run_id_backtest_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_results"),
        sa.UniqueConstraint("run_id", name="uq_backtest_results_run_id"),
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(18, 2), nullable=False),
        sa.Column("cash", sa.Numeric(18, 2), nullable=False),
        sa.Column("positions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_portfolio_snapshots"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("backtest_results")
    op.drop_table("backtest_runs")
    op.drop_table("signals")
    op.drop_table("indicator_cache")
    op.drop_index("ix_price_candles_instrument_date", table_name="price_candles")
    op.drop_table("price_candles")
    op.drop_index("ix_instruments_ticker", table_name="instruments")
    op.drop_table("instruments")
