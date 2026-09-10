"""Shared append-only provenance base: canonical JSON is the hashed byte domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Record(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("owners.id"), nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    hash_format: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def provenance_checks(table: str, *, prompt: bool = False, limit: int = 262144) -> tuple[Any, ...]:
    checks: tuple[Any, ...] = (
        UniqueConstraint("owner_id", "id", name=f"uq_{table}_owner_id_id"),
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("owner_id > 0", name="owner_positive"),
        CheckConstraint("hash_format = 1", name="hash_format_v1"),
        CheckConstraint(
            f"octet_length(canonical_json) BETWEEN 1 AND {limit}", name="content_bounded"
        ),
        CheckConstraint(
            "content_hash = public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')",
            name="hash_matches",
        ),
    )
    if not prompt:
        checks += (
            CheckConstraint(
                "canonical_json = public.tamforge_provenance_canonical(canonical_json::jsonb)",
                name="canonical_bytes",
            ),
        )
    return checks
