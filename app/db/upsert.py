"""Dialect-aware INSERT … ON CONFLICT DO UPDATE factory.

Centralises the SQLite (index_elements) vs PostgreSQL (constraint name)
branching that would otherwise be duplicated in every module that upserts.
"""
from __future__ import annotations

from app.core.config import get_settings


def build_upsert(
    model,
    records: list[dict],
    *,
    index_elements: list[str],
    constraint_name: str,
    update_fields: list[str],
):
    """Return a dialect-aware INSERT … ON CONFLICT DO UPDATE statement.

    Args:
        model:            SQLAlchemy ORM model class (e.g. PriceCandle).
        records:          Rows to insert.
        index_elements:   Column names used as the conflict target on SQLite.
                          Must match an actual UNIQUE index on those columns.
                          Do NOT include JSON/TEXT columns — SQLite cannot
                          use them in a partial unique index.
        constraint_name:  Named unique constraint used on PostgreSQL.
        update_fields:    Column names to overwrite on conflict.
    """
    settings = get_settings()

    if settings.is_sqlite:
        from sqlalchemy.dialects.sqlite import insert as _ins
        stmt = _ins(model).values(records)
        return stmt.on_conflict_do_update(
            index_elements=index_elements,
            set_={f: getattr(stmt.excluded, f) for f in update_fields},
        )

    from sqlalchemy.dialects.postgresql import insert as _ins
    stmt = _ins(model).values(records)
    return stmt.on_conflict_do_update(
        constraint=constraint_name,
        set_={f: getattr(stmt.excluded, f) for f in update_fields},
    )
