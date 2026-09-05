"""Atomic frozen invocation registration and append-only audit repositories."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol.agents import AttemptTextReference

from ..learning.models import ActivityInstance, Attempt
from .contracts import (
    ImmutableVersionConflict,
    InvalidProvenance,
    Lifecycle,
    ProvenanceNotFound,
    RunRequest,
    State,
    StateConflict,
    ToolAudit,
    validate_transition,
)
from .hashing import canonical_bytes, digest
from .models import AgentToolCall, ModelRun, ModelRunContextItem, ModelRunEvent
from .prompt_registry import lock_owner, verified

# Scalar fields or one array index only. Task metadata is intentionally absent.
LEARNER_FIELDS = {
    "reading": {"key_ideas", "boundary_or_failure", "tam_customer_example", "unresolved_question"},
    "sql": {"query", "result", "validation", "explanation", "business_meaning"},
    "case": {
        "discovery_questions",
        "assumptions",
        "working_notes",
        "final_artifact",
        "decisions",
        "risks",
        "unresolved_questions",
    },
    "writing": {"draft_markdown", "self_edit_notes"},
    "pipeline": {"completed_action", "artifact_summary", "next_action"},
}


def resolve_attempt_text(original: str, reference: AttemptTextReference) -> str:
    """Hash the exact prepared slice; references cannot select task metadata."""
    try:
        output = json.loads(original)["output"]
        parts = reference.json_pointer.split("/")
        if len(parts) not in (3, 4) or parts[1] != "output":
            raise InvalidProvenance()
        if parts[2] not in LEARNER_FIELDS.get(output["kind"], set()):
            raise InvalidProvenance()
        value = output[parts[2]]
        if len(parts) == 4:
            if not isinstance(value, list) or not re.fullmatch(r"0|[1-9][0-9]*", parts[3]):
                raise InvalidProvenance()
            value = value[int(parts[3])]
        if not isinstance(value, str) or reference.end_codepoint > len(value):
            raise InvalidProvenance()
        return sha256(
            value[reference.start_codepoint : reference.end_codepoint].encode()
        ).hexdigest()
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        raise InvalidProvenance() from None


@dataclass(frozen=True)
class CompleteRun:
    header: ModelRun
    context: tuple[ModelRunContextItem, ...]
    events: tuple[ModelRunEvent, ...]
    tools: tuple[AgentToolCall, ...]


def _record_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = canonical_bytes(payload)
    return {"canonical_json": data.decode(), "content_hash": sha256(data).digest()}


class ModelRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register(self, request: RunRequest) -> ModelRun:
        try:
            # Revalidate to catch model_construct/model_copy bypasses at this boundary.
            request = RunRequest.model_validate(request.model_dump())
            async with self.session.begin():
                await lock_owner(self.session, request.owner_id)
                activity = await self.session.scalar(
                    select(ActivityInstance.id)
                    .where(
                        ActivityInstance.owner_id == request.owner_id,
                        ActivityInstance.id == request.activity_id,
                    )
                    .with_for_update()
                )
                attempt = await self.session.scalar(
                    select(Attempt).where(
                        Attempt.owner_id == request.owner_id,
                        Attempt.id == request.attempt.id,
                        Attempt.activity_instance_id == request.activity_id,
                    )
                )
                if activity is None or attempt is None or attempt.original_text is None:
                    raise InvalidProvenance()
                if attempt.commitment_hash.hex() != request.attempt.content_hash:
                    raise InvalidProvenance()
                source_hash = sha256(attempt.original_text.encode()).hexdigest()
                items = []
                for item in request.context:
                    if resolve_attempt_text(attempt.original_text, item.reference) != (
                        item.prepared_input_hash
                    ):
                        raise InvalidProvenance()
                    items.append(
                        {
                            "format": 1,
                            "kind": "context",
                            "profile": "committed-attempt-text-v1",
                            "owner_id": request.owner_id,
                            "activity_id": request.activity_id,
                            "source_version": 1,
                            "source_hash": source_hash,
                            **item.model_dump(mode="json"),
                        }
                    )
                header = {
                    "format": 1,
                    "kind": "run",
                    **request.model_dump(mode="json", exclude={"context"}),
                    "manifest": [digest(item) for item in items],
                }
                header["manifest_hash"] = digest(header["manifest"])
                record_data = _record_data(header)
                existing = await self.session.scalar(
                    select(ModelRun).where(
                        ModelRun.owner_id == request.owner_id,
                        ModelRun.invocation_key == request.invocation_key,
                    )
                )
                if existing is not None:
                    if verified(existing).canonical_json != record_data["canonical_json"]:
                        raise ImmutableVersionConflict()
                    return existing
                run = ModelRun(owner_id=request.owner_id, **record_data)
                self.session.add(run)
                await self.session.flush()
                for context_payload in items:
                    self.session.add(
                        ModelRunContextItem(
                            owner_id=request.owner_id,
                            run_id=run.id,
                            **_record_data(context_payload),
                        )
                    )
                await self.session.flush()
                return run
        except (SQLAlchemyError, ValidationError):
            raise InvalidProvenance() from None

    async def _locked_run(self, owner_id: int, run_hash: bytes) -> ModelRun:
        if (
            type(owner_id) is not int
            or owner_id <= 0
            or type(run_hash) is not bytes
            or len(run_hash) != 32
        ):
            raise InvalidProvenance()
        return verified(
            await self.session.scalar(
                select(ModelRun)
                .where(ModelRun.owner_id == owner_id, ModelRun.content_hash == run_hash)
                .with_for_update()
            )
        )

    async def append_event(
        self,
        *,
        owner_id: int,
        run_hash: bytes,
        expected_sequence: int,
        expected_state: State,
        event: Lifecycle,
    ) -> ModelRunEvent:
        try:
            event = Lifecycle.model_validate(event.model_dump())
            if type(expected_sequence) is not int or expected_sequence < 0:
                raise InvalidProvenance()
            async with self.session.begin():
                run = await self._locked_run(owner_id, run_hash)
                latest = await self.session.scalar(
                    select(ModelRunEvent)
                    .where(ModelRunEvent.run_id == run.id)
                    .order_by(ModelRunEvent.sequence.desc())
                    .limit(1)
                )
                sequence = latest.sequence if latest else 0
                state = (
                    json.loads(latest.canonical_json)["event"]["state"] if latest else "registered"
                )
                if (sequence, state) != (expected_sequence, expected_state):
                    raise StateConflict()
                validate_transition(state, event)
                payload = {
                    "format": 1,
                    "kind": "event",
                    "owner_id": owner_id,
                    "run_hash": run_hash.hex(),
                    "sequence": sequence + 1,
                    "expected_state": expected_state,
                    "event": event.model_dump(mode="json"),
                }
                row = ModelRunEvent(owner_id=owner_id, run_id=run.id, **_record_data(payload))
                self.session.add(row)
                await self.session.flush()
                return row
        except (SQLAlchemyError, ValidationError):
            raise InvalidProvenance() from None

    async def append_tool(
        self, *, owner_id: int, run_hash: bytes, expected_sequence: int, audit: ToolAudit
    ) -> AgentToolCall:
        try:
            audit = ToolAudit.model_validate(audit.model_dump())
            if type(expected_sequence) is not int or expected_sequence < 0:
                raise InvalidProvenance()
            async with self.session.begin():
                run = await self._locked_run(owner_id, run_hash)
                latest = await self.session.scalar(
                    select(AgentToolCall)
                    .where(AgentToolCall.run_id == run.id)
                    .order_by(AgentToolCall.sequence.desc())
                    .limit(1)
                )
                sequence = latest.sequence if latest else 0
                if sequence != expected_sequence:
                    raise StateConflict()
                payload = {
                    "format": 1,
                    "kind": "tool",
                    "owner_id": owner_id,
                    "run_hash": run_hash.hex(),
                    "sequence": sequence + 1,
                    "audit": audit.model_dump(mode="json"),
                }
                canonical_bytes(payload, limit=16384)
                row = AgentToolCall(owner_id=owner_id, run_id=run.id, **_record_data(payload))
                self.session.add(row)
                await self.session.flush()
                return row
        except (SQLAlchemyError, ValidationError):
            raise InvalidProvenance() from None

    async def read(self, *, owner_id: int, run_hash: bytes) -> CompleteRun:
        try:
            async with self.session.begin():
                run = await self._locked_run(owner_id, run_hash)
                contexts = tuple(
                    verified(row)
                    for row in (
                        await self.session.scalars(
                            select(ModelRunContextItem)
                            .where(ModelRunContextItem.run_id == run.id)
                            .order_by(ModelRunContextItem.ordinal)
                        )
                    ).all()
                )
                events = tuple(
                    verified(row)
                    for row in (
                        await self.session.scalars(
                            select(ModelRunEvent)
                            .where(ModelRunEvent.run_id == run.id)
                            .order_by(ModelRunEvent.sequence)
                        )
                    ).all()
                )
                tools = tuple(
                    verified(row)
                    for row in (
                        await self.session.scalars(
                            select(AgentToolCall)
                            .where(AgentToolCall.run_id == run.id)
                            .order_by(AgentToolCall.sequence)
                        )
                    ).all()
                )
                if json.loads(run.canonical_json)["manifest"] != [
                    item.content_hash.hex() for item in contexts
                ]:
                    raise InvalidProvenance()
                return CompleteRun(run, contexts, events, tools)
        except SQLAlchemyError:
            raise ProvenanceNotFound() from None
