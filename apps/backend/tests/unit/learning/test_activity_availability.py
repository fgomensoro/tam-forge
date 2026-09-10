"""Every activity command turns a database failure into ActivityUnavailable."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tamforge_backend.learning.enums import IncompleteClassification
from tamforge_backend.learning.service import ActivityService, ActivityUnavailable

ANSWER = "I walked through the plan out loud."

COMMANDS: dict[str, dict[str, object]] = {
    "get_activity": {"owner_id": 1, "activity_id": 7},
    "start": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "idempotency_key": "start-1",
    },
    "heartbeat": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "client_sequence": 1,
        "idempotency_key": "heartbeat-1",
    },
    "pause": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "client_sequence": 1,
        "idempotency_key": "pause-1",
    },
    "resume": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "idempotency_key": "resume-1",
    },
    "classify_incomplete": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "classification": IncompleteClassification.REQUIRED,
        "stronger_evidence_id": None,
        "idempotency_key": "classify-1",
    },
    "presign_artifact": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "artifact_class": "output_document",
        "sha256": "a" * 64,
        "byte_length": 128,
        "content_type": "text/markdown",
        "original_filename": "answer.md",
        "idempotency_key": "presign-1",
    },
    "confirm_artifact": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "upload_idempotency_key": "presign-1",
        "object_key": "owners/1/activities/7/answer.md",
        "idempotency_key": "confirm-1",
    },
    "set_source_visibility": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "hidden": True,
        "idempotency_key": "visibility-1",
    },
    "commit_output": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "client_sequence": 1,
        "output": {},
        "artifact_refs": (),
        "parent_attempt_id": None,
        "idempotency_key": "commit-1",
    },
    "submit_self_review": {
        "owner_id": 1,
        "activity_id": 7,
        "expected_version": 1,
        "main_answer": ANSWER,
        "did_well": ANSWER,
        "structure_weakness": ANSWER,
        "vague_points": ANSWER,
        "hesitation_points": ANSWER,
        "change_next": ANSWER,
        "self_score": 3,
        "idempotency_key": "self-review-1",
    },
}


class DroppedConnectionSession:
    """Just enough AsyncSession to fail every statement, transaction still working."""

    def begin(self):
        class Transaction:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return Transaction()

    async def execute(self, statement: object, *args: object, **values: object) -> object:
        del statement, args, values
        raise SQLAlchemyError("SELECT ... WHERE owner_id = %(owner_id)s", {"owner_id": 1})

    async def scalar(self, statement: object, *args: object, **values: object) -> object:
        return await self.execute(statement, *args, **values)

    async def flush(self) -> None:
        await self.execute(None)

    async def rollback(self) -> None:
        await self.execute(None)

    def add(self, row: object) -> None:
        del row


class StubObjectStore:
    """Presign and confirm require a store before they reach the database."""

    async def stat(self, object_key: str) -> None:
        del object_key
        return None


def test_every_public_command_is_covered() -> None:
    public = {
        name
        for name, _ in inspect.getmembers(ActivityService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == set(COMMANDS)


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_database_failure_becomes_activity_unavailable(command: str) -> None:
    service = ActivityService(
        DroppedConnectionSession(),  # type: ignore[arg-type]
        object_store=StubObjectStore(),  # type: ignore[arg-type]
    )
    with pytest.raises(ActivityUnavailable) as caught:
        asyncio.run(getattr(service, command)(**COMMANDS[command]))
    assert caught.value.__cause__ is None
    assert "owner_id" not in str(caught.value)
