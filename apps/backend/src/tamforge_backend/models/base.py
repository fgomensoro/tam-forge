"""Shared metadata and UTC fields; schema lifecycle is Alembic-only."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, event, func
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return an aware UTC timestamp for Python-side defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base imported by both application models and Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class SchemaLifecycleError(RuntimeError):
    """Raised when code bypasses Alembic for schema creation or destruction."""


def reject_direct_schema_lifecycle(
    metadata: MetaData,
    connection: Connection,
    **kwargs: object,
) -> None:
    """Fail before create_all/drop_all can emit partial schema DDL."""
    del metadata, connection, kwargs
    raise SchemaLifecycleError("schema lifecycle must use Alembic migrations")


event.listen(Base.metadata, "before_create", reject_direct_schema_lifecycle)
event.listen(Base.metadata, "before_drop", reject_direct_schema_lifecycle)


class TimestampMixin:
    """Consistent aware creation and update timestamps for future models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )
