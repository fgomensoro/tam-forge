"""Owner-scoped immutable publication and verified hash lookup."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TypeVar, cast

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol import EnglishAnalysisV1, TAMAnalysisV1

from ..auth.models import Owner
from .contracts import (
    ImmutableVersionConflict,
    InvalidProvenance,
    PinnedVersion,
    ProvenanceNotFound,
    Publication,
)
from .hashing import canonical_bytes, prompt_bytes
from .models import OutputSchemaVersion, PromptVersion, Record, RubricVersionHash, snapshot_record

R = TypeVar("R", bound=Record)


async def lock_owner(session: AsyncSession, owner_id: int) -> None:
    if type(owner_id) is not int or owner_id <= 0:
        raise InvalidProvenance()
    owner = await session.scalar(select(Owner.id).where(Owner.id == owner_id).with_for_update())
    if owner is None:
        raise ProvenanceNotFound()


def verified[R: Record](row: R | None) -> R:
    if row is None:
        raise ProvenanceNotFound()
    if row.hash_format != 1 or sha256(row.canonical_json.encode()).digest() != row.content_hash:
        raise InvalidProvenance()
    return row


class PromptRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish_prompt(
        self, *, owner_id: int, key: str, version: str, content: str
    ) -> PromptVersion:
        try:
            identity = Publication(owner_id=owner_id, key=key, version=version)
            data = prompt_bytes(content)
        except ValueError:
            raise InvalidProvenance() from None
        return await self._publish(PromptVersion, identity, data)

    async def publish_schema(
        self, *, owner_id: int, key: str, version: str, content: dict[str, object]
    ) -> OutputSchemaVersion:
        try:
            identity = Publication(owner_id=owner_id, key=key, version=version)
            data = canonical_bytes(content, limit=1048576)
            if content.get("$id") != key:
                raise InvalidProvenance()
        except ValueError:
            raise InvalidProvenance() from None
        return await self._publish(OutputSchemaVersion, identity, data)

    async def publish_analysis_schemas(self, *, owner_id: int) -> tuple[OutputSchemaVersion, ...]:
        """Publish the exact #54 schema snapshots with their actual URNs."""
        rows = []
        for contract in (EnglishAnalysisV1, TAMAnalysisV1):
            schema = contract.model_json_schema()
            rows.append(
                await self.publish_schema(
                    owner_id=owner_id, key=schema["$id"], version="v1", content=schema
                )
            )
        return tuple(rows)

    async def _publish(self, model: type[R], identity: Publication, data: bytes) -> R:
        try:
            async with self.session.begin():
                await lock_owner(self.session, identity.owner_id)
                # Both concrete registry models expose key/version.
                table = model.__table__
                row = await self.session.scalar(
                    select(model).where(
                        model.owner_id == identity.owner_id,
                        table.c.key == identity.key,
                        table.c.version == identity.version,
                    )
                )
                if row is not None:
                    if verified(row).canonical_json.encode() != data:
                        raise ImmutableVersionConflict()
                    return snapshot_record(row)
                row = model(
                    owner_id=identity.owner_id,
                    key=identity.key,
                    version=identity.version,
                    canonical_json=data.decode(),
                    content_hash=sha256(data).digest(),
                )
                self.session.add(row)
                await self.session.flush()
                return snapshot_record(row)
        except SQLAlchemyError:
            raise InvalidProvenance() from None

    async def lookup(
        self, *, owner_id: int, content_hash: bytes, kind: str
    ) -> tuple[PromptVersion | OutputSchemaVersion, ...]:
        if (
            type(owner_id) is not int
            or owner_id <= 0
            or type(content_hash) is not bytes
            or len(content_hash) != 32
        ):
            raise InvalidProvenance()
        model: type[PromptVersion] | type[OutputSchemaVersion]
        if kind == "prompt":
            model = PromptVersion
        elif kind == "schema":
            model = OutputSchemaVersion
        else:
            raise InvalidProvenance()
        try:
            async with self.session.begin():
                rows = (
                    await self.session.scalars(
                        select(model)
                        .where(model.owner_id == owner_id, model.content_hash == content_hash)
                        .order_by(model.id)
                    )
                ).all()
                if not rows:
                    raise ProvenanceNotFound()
                return tuple(
                    cast(PromptVersion | OutputSchemaVersion, snapshot_record(verified(row)))
                    for row in rows
                )
        except SQLAlchemyError:
            raise InvalidProvenance() from None

    async def bind_rubric(self, *, owner_id: int, rubric_id: int) -> RubricVersionHash:
        try:
            PinnedVersion(id=rubric_id, content_hash="0" * 64)
            async with self.session.begin():
                await lock_owner(self.session, owner_id)
                payload = await self.session.scalar(
                    text("SELECT public.tamforge_provenance_rubric(:owner, :rubric)"),
                    {"owner": owner_id, "rubric": rubric_id},
                )
                if payload is None:
                    raise InvalidProvenance()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                data = canonical_bytes(payload)
                row = await self.session.scalar(
                    select(RubricVersionHash).where(
                        RubricVersionHash.owner_id == owner_id,
                        RubricVersionHash.rubric_id == rubric_id,
                    )
                )
                if row is not None:
                    if verified(row).canonical_json.encode() != data:
                        raise ImmutableVersionConflict()
                    return snapshot_record(row)
                row = RubricVersionHash(
                    owner_id=owner_id,
                    canonical_json=data.decode(),
                    content_hash=sha256(data).digest(),
                )
                self.session.add(row)
                await self.session.flush()
                return snapshot_record(row)
        except (SQLAlchemyError, ValidationError):
            raise InvalidProvenance() from None
