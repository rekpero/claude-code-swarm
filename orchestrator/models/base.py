"""Declarative base, shared mixins, and column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _uuid_str() -> str:
    return str(uuid.uuid4())


def uuid_pk() -> Mapped[str]:
    """A string UUID primary key column.

    UUIDs (not autoincrement ints) avoid cross-tenant id enumeration and keep
    ids stable across environments.
    """
    return mapped_column(String(36), primary_key=True, default=_uuid_str)


class TimestampMixin:
    """Adds created_at / updated_at columns maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
