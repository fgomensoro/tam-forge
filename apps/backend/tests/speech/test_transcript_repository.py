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
from sqlalchemy.exc import IntegrityError, OperationalError
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


class _Rendezvous:
    """Lets exactly `count` `scalar()` calls block until all of them have
    arrived, then releases every one of them at once -- simulating two
    `store()` calls whose existing-row SELECT both run before either has
    written anything. A later, unpaired call (`store`'s own retry once the
    race is lost) finds the rendezvous already spent and returns immediately
    instead of waiting for a partner that will never arrive.
    """

    def __init__(self, count: int) -> None:
        self._count = count
        self._arrived = 0
        self._released = asyncio.Event()

    async def wait(self) -> None:
        self._arrived += 1
        if self._arrived >= self._count:
            self._released.set()
        else:
            await self._released.wait()


class FakeSession:
    """A Python list plus statement introspection; no real database involved.

    `scalar`/`scalars` read the compiled statement's bound parameters and filter
    `rows` by column equality -- all the repository's queries ever do. `flush`
    backfills what PostgreSQL would assign on insert: the identity `id`, the
    `hash_format`/`created_at` defaults, and -- by parsing the row's own
    `canonical_json`, exactly as the real generated-column expression reads it --
    every `Computed` column. It also enforces the one real constraint the
    repository's own `store` logic has to cope with,
    `uq_speech_transcripts_recording_track`, raising the same `IntegrityError`
    PostgreSQL would on a colliding insert -- everything else (the hash
    constraint, the immutability triggers) stays out of scope, per this file's
    module docstring. `begin` models commit/rollback by removing exactly the
    rows added during a transaction that raises (not by truncating on list
    length, which would also erase a *different*, already-committed
    transaction's rows when two `store()` calls are genuinely interleaved via
    `asyncio.gather` -- see the concurrency tests below). Tracking "this
    transaction's own rows" as a plain LIFO stack, rather than something
    concurrency-safe like a `contextvars.ContextVar`, is safe here specifically
    because nothing in this fake ever awaits inside `add`/`flush`, so two
    `begin()` blocks can never interleave their *writes*, only the reads
    gated by `race` below -- a `begin()` entered while another is still open
    always exits before that outer one does.
    """

    def __init__(self, *, race: _Rendezvous | None = None) -> None:
        self.rows: list[object] = []
        self.calls: list[str] = []
        self._next_id = 1
        self._race = race
        self._pending: list[list[object]] = []
        self.fail_next_flush: Exception | None = None

    def add(self, row: object) -> None:
        self.calls.append("add")
        self.rows.append(row)
        self._pending[-1].append(row)

    async def flush(self) -> None:
        self.calls.append("flush")
        if self.fail_next_flush is not None:
            error, self.fail_next_flush = self.fail_next_flush, None
            raise error
        for row in self.rows:
            if getattr(row, "id", None) is not None:
                continue
            parsed = json.loads(row.canonical_json)
            if isinstance(row, SpeechTranscript) and any(
                isinstance(other, SpeechTranscript)
                and other.id is not None
                and other.owner_id == row.owner_id
                and other.recording_id == parsed.get("recording_id")
                and other.track == parsed.get("track")
                for other in self.rows
            ):
                raise IntegrityError(
                    "INSERT INTO speech_transcripts ...",
                    {},
                    Exception(
                        "duplicate key value violates unique constraint "
                        '"uq_speech_transcripts_recording_track"'
                    ),
                )
            row.id = self._next_id
            self._next_id += 1
            row.hash_format = 1
            row.created_at = datetime.now(UTC)
            for column in type(row).__table__.columns:
                if column.computed is not None:
                    setattr(row, column.name, parsed.get(column.name))

    @asynccontextmanager
    async def begin(self):
        self.calls.append("begin")
        added: list[object] = []
        self._pending.append(added)
        try:
            yield self
        except BaseException:
            for row in added:
                self.rows.remove(row)
            raise
        finally:
            self._pending.pop()

    async def scalar(self, statement: object) -> object | None:
        self.calls.append("scalar")
        matches = self._matches(statement)
        if self._race is not None:
            await self._race.wait()
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


def test_concurrent_identical_submissions_replay_the_same_row_instead_of_conflicting() -> None:
    """Two `store()` calls racing on the same identity -- both see no
    existing row (forced by `race`), both attempt to insert, and PostgreSQL's
    `uq_speech_transcripts_recording_track` (simulated by `FakeSession.flush`)
    lets only one through. Since the two bodies are byte-identical, the loser
    must recover this as a clean replay, not `TranscriptConflict`.
    """

    async def exercise() -> None:
        session = FakeSession(race=_Rendezvous(2))
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        body = transcript_body()

        first, second = await asyncio.gather(
            repository.store(owner_id=1, recording=recording, track="microphone", body=body),
            repository.store(owner_id=1, recording=recording, track="microphone", body=body),
        )

        assert first.id == second.id
        assert first.content_hash == second.content_hash
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 1
        # Two flush attempts happened -- the winner's, which succeeded, and
        # the loser's, which hit the simulated IntegrityError. If `race` had
        # failed to force the interleaving, the second store() would have
        # seen the first's row via the ordinary existing-row check and never
        # reached flush() at all, so this pins down that the race was
        # genuinely exercised, not sidestepped.
        assert session.calls.count("flush") == 2

    asyncio.run(exercise())


def test_concurrent_differing_submissions_the_loser_gets_transcript_conflict() -> None:
    """Same race as above, but the two bodies differ. The loser must see
    `TranscriptConflict`, and neither side may ever surface the raw
    `IntegrityError` `FakeSession.flush` raises on the collision.
    """

    async def exercise() -> None:
        session = FakeSession(race=_Rendezvous(2))
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        results = await asyncio.gather(
            repository.store(
                owner_id=1,
                recording=recording,
                track="microphone",
                body=transcript_body(text="version A"),
            ),
            repository.store(
                owner_id=1,
                recording=recording,
                track="microphone",
                body=transcript_body(text="version B"),
            ),
            return_exceptions=True,
        )

        winners = [item for item in results if isinstance(item, SpeechTranscript)]
        conflicts = [item for item in results if isinstance(item, TranscriptConflict)]
        # Every result is accounted for as exactly one of these two outcomes --
        # nothing else, and in particular no raw IntegrityError, came out.
        assert len(winners) + len(conflicts) == len(results) == 2
        assert len(winners) == 1
        assert len(conflicts) == 1
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 1
        # As above: two flush attempts pins down that both sides genuinely
        # raced rather than one seeing the other's row via the ordinary
        # existing-row check.
        assert session.calls.count("flush") == 2

    asyncio.run(exercise())


def test_append_correction_never_leaks_a_raw_sqlalchemy_error() -> None:
    """`append_correction` has no identity to race on, but an unexpected
    `SQLAlchemyError` mid-flush (a dropped connection, a statement timeout --
    modeled here with `OperationalError`, deliberately not the `IntegrityError`
    the two tests above cover, to prove the `except` isn't narrowed to just
    that one subtype) must still come out as `TranscriptConflict`, never raw.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        session.fail_next_flush = OperationalError(
            "INSERT INTO speech_transcript_corrections ...", {}, Exception("connection lost")
        )

        with pytest.raises(TranscriptConflict):
            await repository.append_correction(
                owner_id=1, transcript=transcript, body=correction_body()
            )
        # The failed attempt left no partial row behind.
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 0

    asyncio.run(exercise())
