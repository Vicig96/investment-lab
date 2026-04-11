"""Cross-database custom SQLAlchemy types.

- GUID:        UUID in PostgreSQL, CHAR(36) in SQLite.
- JSONBCompat: JSONB in PostgreSQL, JSON everywhere else.
"""
from __future__ import annotations

import uuid as _uuid

from sqlalchemy import types


class GUID(types.TypeDecorator):
    """Platform-independent UUID type.

    Stores as PostgreSQL native UUID when available; falls back to CHAR(36)
    for SQLite and other backends.  Always returns ``uuid.UUID`` objects.
    """

    impl = types.CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(types.CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, _uuid.UUID):
            value = _uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))

    def coerce_compared_value(self, op, value):
        return self.impl


class JSONBCompat(types.TypeDecorator):
    """Uses PostgreSQL JSONB when available; plain JSON elsewhere."""

    impl = types.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(types.JSON())
