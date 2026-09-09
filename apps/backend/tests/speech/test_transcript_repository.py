"""Database-free repository tests: a fake AsyncSession stands in for PostgreSQL.

The generated columns (`recording_id`, `track`, `transcript_id`), the hash
constraint, and the immutability triggers are PostgreSQL-side guarantees covered
separately by the integration suite. This file exercises only what the Python
repository itself decides: canonicalization, hashing, idempotent replay, conflict
detection, owner isolation, and ordering.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from tamforge_backend.agents.hashing import canonical_bytes
from tamforge_backend.speech.contracts import (
    TranscriptConflict,
    TranscriptNotFound,
    TranscriptTooLarge,
)
from tamforge_backend.speech.models import (
    CORRECTION_BODY_LIMIT,
    TRANSCRIPT_BODY_LIMIT,
    SpeechTranscript,
    SpeechTranscriptCorrection,
)
from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class FakeSession:
    """A Python list plus statement introspection; no real database involved.

    `scalar`/`scalars` read the compiled statement's bound parameters and filter
    `rows` by column equality -- all the repository's queries ever do. `flush`
    backfills what PostgreSQL would assign on insert: the identity `id`, the
    `hash_format`/`created_at` defaults, and -- by parsing the row's own
    `canonical_json`, exactly as the real generated-column expression reads it --
    every `Computed` column. `begin` models commit/rollback by trimming rows
    added during a transaction that raises, matching
    ``tests/unit/agents/test_model_runs.py``.
    """

    def __init__(self) -> None:
        self.rows: list[object] = []
        self.calls: list[str] = []
        self._next_id = 1

    def add(self, row: object) -> None:
        self.calls.append("add")
        self.rows.append(row)

    async def flush(self) -> None:
        self.calls.append("flush")
        for row in self.rows:
            if getattr(row, "id", None) is not None:
                continue
            row.id = self._next_id
            self._next_id += 1
            row.hash_format = 1
            row.created_at = datetime.now(UTC)
            parsed = json.loads(row.canonical_json)
            for column in type(row).__table__.columns:
                if column.computed is not None:
                    setattr(row, column.name, parsed.get(column.name))

    @asynccontextmanager
    async def begin(self):
        self.calls.append("begin")
        committed = len(self.rows)
        try:
            yield self
        except BaseException:
            del self.rows[committed:]
            raise

    async def scalar(self, statement: object) -> object | None:
        self.calls.append("scalar")
        matches = self._matches(statement)
        return matches[0] if matches else None

    async def scalars(self, statement: object) -> _ScalarResult:
        self.calls.append("scalars")
        return _ScalarResult(self._matches(statement))

    def _matches(self, statement: object) -> list[object]:
        model = statement.column_descriptions[0]["type"]
        params = statement.compile().params
        return [
            row
            for row in self.rows
            if isinstance(row, model)
            and all(
                getattr(row, key.rsplit("_", 1)[0], object()) == value
                for key, value in params.items()
            )
        ]


def transcript_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "track": "microphone",
        "text": "hello there",
    }
    body.update(overrides)
    return body


def correction_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "segment_index": 0,
        "word_start_index": 0,
        "word_end_index": 1,
        "original_text": "helo",
        "corrected_text": "hello",
        "reason": "misheard_term",
    }
    body.update(overrides)
    return body


def test_stored_content_hash_matches_canonical_bytes_sha256() -> None:
    async def exercise() -> None:
        repository = SqlAlchemyTranscriptRepository(FakeSession())
        recording = SimpleNamespace(id=42)
        body = transcript_body()

        stored = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=body
        )

        expected = sha256(
            canonical_bytes(
                {**body, "recording_id": 42, "track": "microphone"},
                limit=TRANSCRIPT_BODY_LIMIT,
            )
        ).digest()
        assert stored.content_hash == expected

    asyncio.run(exercise())


def test_identical_resubmission_replays_the_stored_row_instead_of_inserting_twice() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        body = transcript_body()

        first = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=body
        )
        second = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=body
        )

        assert first.id == second.id
        assert first.content_hash == second.content_hash
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 1

    asyncio.run(exercise())


def test_conflicting_resubmission_on_the_same_recording_and_track_is_refused() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        with pytest.raises(TranscriptConflict):
            await repository.store(
                owner_id=1,
                recording=recording,
                track="microphone",
                body=transcript_body(text="a different transcript"),
            )
        # The refused attempt never inserted a second row.
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 1

    asyncio.run(exercise())


def test_oversized_body_is_refused_before_the_session_is_touched() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        body = transcript_body(text="x" * TRANSCRIPT_BODY_LIMIT)

        with pytest.raises(TranscriptTooLarge):
            await repository.store(owner_id=1, recording=recording, track="microphone", body=body)

        assert session.calls == []
        assert session.rows == []

    asyncio.run(exercise())


def test_by_recording_never_returns_another_owners_transcript() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        assert len(await repository.by_recording(owner_id=1, recording_id=42)) == 1
        assert await repository.by_recording(owner_id=2, recording_id=42) == ()

    asyncio.run(exercise())


def test_append_correction_rejects_a_transcript_owned_by_someone_else() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        with pytest.raises(TranscriptNotFound):
            await repository.append_correction(
                owner_id=2, transcript=transcript, body=correction_body()
            )

    asyncio.run(exercise())


def test_oversized_correction_is_refused_before_the_session_is_touched() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        calls_before = list(session.calls)
        body = correction_body(original_text="x" * CORRECTION_BODY_LIMIT)

        with pytest.raises(TranscriptTooLarge):
            await repository.append_correction(owner_id=1, transcript=transcript, body=body)

        assert session.calls == calls_before
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 0

    asyncio.run(exercise())


def test_corrections_are_returned_in_insertion_order() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        first = await repository.append_correction(
            owner_id=1, transcript=transcript, body=correction_body(reason="misheard_term")
        )
        second = await repository.append_correction(
            owner_id=1,
            transcript=transcript,
            body=correction_body(reason="mistranscribed_number"),
        )

        corrections = await repository.corrections(owner_id=1, transcript_id=transcript.id)

        assert [correction.id for correction in corrections] == [first.id, second.id]

    asyncio.run(exercise())
