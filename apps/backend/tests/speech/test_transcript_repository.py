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
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError, MissingGreenlet, OperationalError
from tamforge_backend.agents.hashing import canonical_bytes
from tamforge_backend.speech.contracts import (
    TranscriptConflict,
    TranscriptNotFound,
    TranscriptTooLarge,
    TranscriptUnavailable,
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


class ExpiringRecording:
    """Stands in for a `recordings.models.Recording` loaded earlier in the
    same request-scoped session `store()` runs against.

    `SimpleNamespace(id=42)` (used everywhere else in this file) has no
    SQLAlchemy instrumentation and therefore no expiration semantics -- it
    cannot fail the way Finding 1's real bug failed. A real
    `AsyncSession.begin()` rollback expires every object in that session's
    identity map, `recording` included; re-reading `.id` afterward needs a
    lazy refresh an `AsyncSession` cannot perform implicitly, and raises
    `MissingGreenlet` -- itself a `SQLAlchemyError` -- before
    `_reconcile_lost_race` ever runs. `FakeSession.begin` flips `expired` on
    every recording passed as its `expires=` argument when one of its
    transactions rolls back, so `.id` raises exactly when the real attribute
    would need an unawaited refresh -- which is what lets the two concurrency
    tests below actually fail if `store` ever again reads `recording.id`
    after the race is lost, instead of the local it is supposed to capture
    before either attempt begins.
    """

    def __init__(self, id: int) -> None:
        self._id = id
        self.expired = False

    @property
    def id(self) -> int:
        if self.expired:
            raise MissingGreenlet(
                "greenlet_spawn has not been called; can't call await_only() here. "
                "Was IO attempted in an unexpected place?"
            )
        return self._id


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
    always exits before that outer one does. `begin` also flips `expired` on
    every `ExpiringRecording` passed as `expires=` when a transaction rolls
    back, mirroring a real `AsyncSession` expiring its whole identity map on
    rollback, not only the rows the failed transaction touched.
    `fail_next_scalar` is `fail_next_flush`'s sibling for the read side, used
    to simulate a transient failure on a SELECT rather than a flush.
    """

    def __init__(
        self,
        *,
        race: _Rendezvous | None = None,
        expires: tuple[ExpiringRecording, ...] = (),
    ) -> None:
        self.rows: list[object] = []
        self.calls: list[str] = []
        self._next_id = 1
        self._race = race
        self._expires = expires
        self._pending: list[list[object]] = []
        self.fail_next_flush: Exception | None = None
        self.fail_next_scalar: Exception | None = None

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
            for expiring in self._expires:
                expiring.expired = True
            raise
        finally:
            self._pending.pop()

    async def scalar(self, statement: object) -> object | None:
        self.calls.append("scalar")
        if self.fail_next_scalar is not None:
            error, self.fail_next_scalar = self.fail_next_scalar, None
            raise error
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

    `recording` is an `ExpiringRecording`, wired into `expires=`, rather than
    the bare `SimpleNamespace` every other test uses: the loser's own
    rollback expires it exactly as a real session would (Finding 1), so this
    test actually fails -- with `MissingGreenlet`, not a clean assertion
    failure -- if `store` ever again reads `recording.id` from inside its
    `except` handler instead of the id it captured before either attempt
    began.
    """

    async def exercise() -> None:
        recording = ExpiringRecording(id=42)
        session = FakeSession(race=_Rendezvous(2), expires=(recording,))
        repository = SqlAlchemyTranscriptRepository(session)
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

    `recording` is an `ExpiringRecording` for the same Finding 1 reason as
    the test above. The loser's `TranscriptConflict` also covers Finding 2:
    it is raised (`_reconcile_lost_race`'s final check) while still
    dynamically nested inside `store`'s `except IntegrityError:` handler, so
    without `from None` Python chains the raw `IntegrityError` onto it as
    `__context__` -- invisible to `str(exc)`, but printed in full by any
    traceback renderer (`logger.exception`, most error trackers), leaking
    exactly the constraint-violation text this module promises never to
    leak.
    """

    async def exercise() -> None:
        recording = ExpiringRecording(id=42)
        session = FakeSession(race=_Rendezvous(2), expires=(recording,))
        repository = SqlAlchemyTranscriptRepository(session)

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

        # Finding 2: the conflict must not chain to the raw IntegrityError.
        # `__suppress_context__` is what `from None` actually sets, and what
        # every traceback renderer checks before printing a chained cause.
        conflict = conflicts[0]
        assert conflict.__suppress_context__ is True
        rendered = "".join(
            traceback.format_exception(type(conflict), conflict, conflict.__traceback__)
        )
        assert "uq_speech_transcripts_recording_track" not in rendered
        assert "duplicate key" not in rendered

    asyncio.run(exercise())


def test_append_correction_surfaces_a_transient_failure_as_unavailable_not_conflict() -> None:
    """`append_correction` has no identity to race on, and -- unlike `store`
    -- no reachable uniqueness collision either:
    `SpeechTranscriptCorrection`'s only constraints are the provenance
    base's trivial `(owner_id, id)` uniqueness on a sequence-assigned `id`,
    and a foreign key to a transcript row that is immutable and never
    deleted. So an unexpected `SQLAlchemyError` mid-flush (a dropped
    connection, a statement timeout -- modeled here with `OperationalError`,
    deliberately not `IntegrityError`, to prove the `except` isn't narrowed
    to just that one subtype) must come out as `TranscriptUnavailable`, with
    a clean exception chain -- never `TranscriptConflict`, which this method
    can no longer raise at all.
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

        with pytest.raises(TranscriptUnavailable) as excinfo:
            await repository.append_correction(
                owner_id=1, transcript=transcript, body=correction_body()
            )
        # The failed attempt left no partial row behind.
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 0
        # Content-free in the chain too, same guarantee as everywhere else
        # in this file that raises `from None`.
        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_append_correction_integrity_error_also_surfaces_as_unavailable() -> None:
    """Even `IntegrityError` specifically -- the one subtype `store` routes
    into a replay-vs-conflict reconciliation -- gets no such treatment here,
    because there is nothing it could legitimately mean:
    `SpeechTranscriptCorrection` carries no constraint a second, concurrent
    insert could ever violate (its `(owner_id, id)` uniqueness is on a
    sequence-assigned `id` that is never reused, and its only other
    constraint is a foreign key to a transcript row that is immutable and
    never deleted, so it cannot vanish out from under a concurrent insert
    either). A real `IntegrityError` here would only be reachable as a
    caller bug, never a race to recover from, so it must surface exactly
    like every other database failure does: as `TranscriptUnavailable`,
    never `TranscriptConflict`. This guards against a future change
    "symmetrizing" this method with `store` by special-casing
    `IntegrityError` back into a conflict outcome that nothing here can
    legitimately produce.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        session.fail_next_flush = IntegrityError(
            "INSERT INTO speech_transcript_corrections ...",
            {},
            Exception("simulated constraint violation"),
        )

        with pytest.raises(TranscriptUnavailable) as excinfo:
            await repository.append_correction(
                owner_id=1, transcript=transcript, body=correction_body()
            )
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 0
        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_store_surfaces_a_transient_database_failure_as_unavailable_not_conflict() -> None:
    """A `SQLAlchemyError` that is not an `IntegrityError` -- a dropped
    connection, a statement timeout, modeled here with `OperationalError` at
    the flush -- is not a uniqueness collision. It must not be routed into
    `_reconcile_lost_race` at all: it surfaces as `TranscriptUnavailable`, a
    distinct, retryable error, never `TranscriptConflict`.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        session.fail_next_flush = OperationalError(
            "INSERT INTO speech_transcripts ...", {}, Exception("connection lost")
        )

        with pytest.raises(TranscriptUnavailable) as excinfo:
            await repository.store(
                owner_id=1, recording=recording, track="microphone", body=transcript_body()
            )

        # Never reached the reconcile path: exactly the one existing-row
        # SELECT ran, not a second one from `_reconcile_lost_race`.
        assert session.calls.count("scalar") == 1
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 0
        # Content-free in the chain too, same guarantee as TranscriptConflict.
        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_reconcile_lost_race_surfaces_a_read_failure_as_unavailable_not_conflict() -> None:
    """`_reconcile_lost_race`'s own re-read can fail for reasons that have
    nothing to do with the collision it exists to resolve -- a dropped
    connection on the retry SELECT itself. That is not "the row still
    differs after a retry", so it must surface as `TranscriptUnavailable`,
    not `TranscriptConflict`.

    Called directly rather than raced through `store()`: reaching this one
    failure deterministically through the public API would need the first
    SELECT to succeed, the flush to fail with `IntegrityError`, and only the
    *second* SELECT to fail -- `FakeSession` only models "the next call
    fails", not "the call after this one", so pinning that down from outside
    would need new, speculative queueing machinery this is the only test
    that would ever use. `_reconcile_lost_race` is exercised through `store`
    elsewhere in this file (both concurrency tests above); this test isolates
    its own except clause instead.
    """

    async def exercise() -> None:
        session = FakeSession()
        session.fail_next_scalar = OperationalError(
            "SELECT ... FROM speech_transcripts ...", {}, Exception("connection lost")
        )
        repository = SqlAlchemyTranscriptRepository(session)

        with pytest.raises(TranscriptUnavailable) as excinfo:
            await repository._reconcile_lost_race(
                owner_id=1, recording_id=42, track="microphone", content_hash=b"\x00" * 32
            )

        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())
