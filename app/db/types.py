"""Cross-database custom SQLAlchemy types.

- GUID:        UUID in PostgreSQL, VARCHAR(36) in SQLite / others.
- JSONBCompat: JSONB in PostgreSQL, JSON everywhere else.
"""
from __future__ import annotations

import uuid as _uuid

from sqlalchemy import types


class GUID(types.TypeDecorator):
    """Platform-independent UUID type.

    Stores as PostgreSQL native UUID when available; falls back to VARCHAR(36)
    for SQLite and other backends.  Always returns ``uuid.UUID`` objects.

    Key design note — coerce_compared_value is NOT overridden.
    The default TypeDecorator implementation returns ``self``, which ensures
    that process_bind_param is invoked for the right-hand side of WHERE
    comparisons such as ``Instrument.id == some_uuid``.  Overriding it to
    return ``self.impl`` (a plain String/CHAR instance) bypasses this and
    causes SQLite to receive a raw uuid.UUID object →
    ``sqlite3.ProgrammingError: type 'UUID' is not supported``.
    """

    impl = types.String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(types.String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return str(value)
        return str(_uuid.UUID(str(value)))  # normalise and validate

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))


class JSONBCompat(types.TypeDecorator):
    """Uses PostgreSQL JSONB when available; plain JSON elsewhere."""

    impl = types.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(types.JSON())
