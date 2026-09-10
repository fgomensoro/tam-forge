"""A dropped database connection must leave a recording route as a 503 problem.

`SqlAlchemyRecordingRepository` is the only place a `SQLAlchemyError` can be
recognised for what it is. Above it nothing catches one: `api.register_routes`
installs a handler per domain error type and none for SQLAlchemy's, and
`observability.middleware` re-raises, so an untranslated failure reaches
Starlette's own server-error handling as a plain-text 500 instead of the
`application/problem+json` 503 the recording routes declare. These tests pin the
translation at that boundary and the status the translated error is rendered
with.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from tamforge_backend.recordings.repository import SqlAlchemyRecordingRepository
from tamforge_backend.recordings.routes import recording_problem_response
from tamforge_backend.recordings.schemas import (
    RecordingCreateCommand,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
)
from tamforge_backend.recordings.service import RecordingUnavailable

RECORDING_ID = UUID("11111111-1111-4111-8111-111111111111")
MICROPHONE_ID = UUID("22222222-2222-4222-8222-222222222222")
SYSTEM_ID = UUID("33333333-3333-4333-8333-333333333333")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "recordings"


def _create_command() -> RecordingCreateCommand:
    return RecordingCreateCommand.model_validate(
        {
            "schema_version": 1,
            "recording_id": str(RECORDING_ID),
            "started_at": "2026-09-01T16:00:00Z",
            "tracks": [
                {
                    "track_id": str(MICROPHONE_ID),
                    "kind": "microphone",
                    "format": {"channel_count": 1},
                    "conversion_version": "tamforge-pcm16-v1",
                },
                {
                    "track_id": str(SYSTEM_ID),
                    "kind": "system_audio",
                    "format": {"channel_count": 2},
                    "conversion_version": "tamforge-pcm16-v1",
                },
            ],
        }
    )


def _part_metadata() -> RecordingPartUploadMetadata:
    plaintext = b"\x01\x00" * 8
    return RecordingPartUploadMetadata.model_validate(
        {
            "schema_version": 1,
            "recording_id": str(RECORDING_ID),
            "track_id": str(MICROPHONE_ID),
            "track_kind": "microphone",
            "format": {"channel_count": 1},
            "sequence": 0,
            "sample_start": 0,
            "sample_count": len(plaintext) // 2,
            "byte_length": len(plaintext),
            "ciphertext_byte_length": len(plaintext) + 16,
            "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
            "ciphertext_sha256": hashlib.sha256(b"c" * 32).hexdigest(),
            "nonce_base64url": base64.urlsafe_b64encode(b"n" * 12).rstrip(b"=").decode(),
            "encryption_version": "aes-256-gcm-hkdf-sha256-v1",
        }
    )


def _seal_command() -> RecordingSealCommand:
    payload = json.loads((FIXTURES / "recording-manifest-v1.json").read_text(encoding="utf-8"))
    return RecordingSealCommand.model_validate(payload)


def _dropped_connection() -> OperationalError:
    """A statement failure carrying exactly what must not reach the client."""
    return OperationalError(
        "SELECT recordings.id FROM recordings WHERE recordings.owner_id = %(owner_id)s",
        {"owner_id": 1},
        Exception("server closed the connection unexpectedly"),
    )


class DroppedConnectionSession:
    """An `AsyncSession` whose every statement fails the way a lost link does.

    `begin` yields without committing so that the statement failure inside the
    block is the error under test rather than a commit failure on the way out;
    `FailingCommitSession` covers the commit separately.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[DroppedConnectionSession]:
        self.calls.append("begin")
        yield self

    async def scalar(self, statement: object) -> object:
        del statement
        self.calls.append("scalar")
        raise _dropped_connection()

    async def scalars(self, statement: object) -> object:
        del statement
        self.calls.append("scalars")
        raise _dropped_connection()

    async def flush(self) -> None:
        self.calls.append("flush")
        raise _dropped_connection()

    def add(self, instance: object) -> None:
        del instance
        self.calls.append("add")


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda repository: repository.create(
                owner_id=1,
                command=_create_command(),
                idempotency_key="create-1",
                request_hash=b"\x00" * 32,
            ),
            id="create",
        ),
        pytest.param(
            lambda repository: repository.reserve_part(
                owner_id=1,
                metadata=_part_metadata(),
                object_key="recording-part/1/part",
                idempotency_key="part-1",
                request_hash=b"\x00" * 32,
            ),
            id="reserve_part",
        ),
        pytest.param(
            lambda repository: repository.finalize_part(
                owner_id=1,
                metadata=_part_metadata(),
                object_key="recording-part/1/part",
                idempotency_key="part-1",
            ),
            id="finalize_part",
        ),
        pytest.param(
            lambda repository: repository.prepare_seal(
                owner_id=1,
                command=_seal_command(),
                idempotency_key="seal-1",
                request_hash=b"\x00" * 32,
            ),
            id="prepare_seal",
        ),
        pytest.param(
            lambda repository: repository.finalize_seal(
                owner_id=1,
                command=_seal_command(),
                idempotency_key="seal-1",
                request_hash=b"\x00" * 32,
                recording_manifest_sha256="ab" * 32,
                manifests=(),
            ),
            id="finalize_seal",
        ),
        pytest.param(
            lambda repository: repository.status(owner_id=1, recording_id=RECORDING_ID),
            id="status",
        ),
        pytest.param(
            lambda repository: repository.pending(owner_id=1),
            id="pending",
        ),
    ],
)
def test_a_dropped_connection_surfaces_as_unavailable_rather_than_a_raw_database_error(
    call: Callable[[SqlAlchemyRecordingRepository], Awaitable[object]],
) -> None:
    """Every public method owes its caller a domain error, not SQLAlchemy's.

    All seven are on a live request path, and each one used to let the raw
    `SQLAlchemyError` out. The chain is suppressed because the rejected
    statement and its bound parameters travel on that error, and the problem
    handler renders whatever reaches it.
    """

    async def exercise() -> None:
        repository = SqlAlchemyRecordingRepository(DroppedConnectionSession())

        with pytest.raises(RecordingUnavailable) as excinfo:
            await call(repository)

        assert excinfo.value.__suppress_context__ is True
        assert excinfo.value.__cause__ is None

    asyncio.run(exercise())


class FailingCommitSession:
    """Every statement lands; the commit `transaction_scope` issues is what drops.

    This is why the translation wraps `transaction_scope` from outside rather
    than sitting inside the block: the commit runs on the way out of the block,
    so a translation placed within it would never see this failure.
    """

    def __init__(self) -> None:
        self.row = SimpleNamespace(
            id=7,
            owner_id=1,
            client_recording_id=RECORDING_ID,
            create_idempotency_key="create-1",
            create_request_hash=b"\x00" * 32,
            create_result_json={
                "schema_version": 1,
                "recording_id": str(RECORDING_ID),
                "state": "reserved",
                "replayed": False,
            },
        )

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[FailingCommitSession]:
        yield self
        raise _dropped_connection()

    async def scalar(self, statement: object) -> object:
        del statement
        return self.row

    async def flush(self) -> None:
        return None


def test_a_failing_commit_surfaces_as_unavailable_rather_than_a_raw_database_error() -> None:
    """A write that only fails at commit is the same outage to the caller."""

    async def exercise() -> None:
        repository = SqlAlchemyRecordingRepository(FailingCommitSession())

        with pytest.raises(RecordingUnavailable) as excinfo:
            await repository.create(
                owner_id=1,
                command=_create_command(),
                idempotency_key="create-1",
                request_hash=b"\x00" * 32,
            )

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_an_unavailable_store_is_rendered_as_the_recording_503_problem() -> None:
    """The translated error reaches the client as the 503 the routes declare."""
    response = recording_problem_response(RecordingUnavailable())

    assert response.status_code == 503
    assert response.media_type == "application/problem+json"
    assert b"recording_unavailable" in response.body
