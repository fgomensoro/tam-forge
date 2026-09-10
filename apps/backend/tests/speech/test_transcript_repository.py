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
from sqlalchemy.sql.functions import count as sql_count
from tamforge_backend.agents.hashing import canonical_bytes
from tamforge_backend.speech.contracts import (
    TranscriptConflict,
    TranscriptNotFound,
    TranscriptTooLarge,
    TranscriptUnavailable,
)
from tamforge_backend.speech.models import (
    CORRECTION_BODY_LIMIT,
    MAX_CORRECTIONS_PER_TRANSCRIPT,
    TRANSCRIPT_BODY_LIMIT,
    SpeechTranscript,
    SpeechTranscriptCorrection,
)
from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository, Written


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
    every `Computed` column. It also enforces the two real constraints the
    repository's own race recovery has to cope with,
    `uq_speech_transcripts_recording_track` and
    `uq_speech_transcript_corrections_content`, raising the same
    `IntegrityError` PostgreSQL would on a colliding insert -- everything else (the hash
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
    to simulate a transient failure on a SELECT rather than a flush. `race` is
    public, not private, so a test whose setup has to write fixtures first --
    a correction needs a transcript on file -- can arm the rendezvous
    afterwards instead of letting those setup reads consume its slots.
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
        self.race = race
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
            if isinstance(row, SpeechTranscriptCorrection) and any(
                isinstance(other, SpeechTranscriptCorrection)
                and other.id is not None
                and other.owner_id == row.owner_id
                and other.transcript_id == parsed.get("transcript_id")
                and other.content_hash == row.content_hash
                for other in self.rows
            ):
                raise IntegrityError(
                    "INSERT INTO speech_transcript_corrections ...",
                    {},
                    Exception(
                        "duplicate key value violates unique constraint "
                        '"uq_speech_transcript_corrections_content"'
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
        if self.race is not None:
            await self.race.wait()
        if isinstance(statement.column_descriptions[0]["expr"], sql_count):
            # `select(func.count(Model.id))` aggregates exactly the rows
            # `_matches` already filtered, so the match count is the answer.
            return len(matches)
        return matches[0] if matches else None

    async def scalars(self, statement: object) -> _ScalarResult:
        self.calls.append("scalars")
        return _ScalarResult(self._matches(statement))

    def _matches(self, statement: object) -> list[object]:
        # "entity" rather than "type": both name the model for `select(Model)`,
        # but an aggregate's "type" is its own result type, not a mapped class.
        model = statement.column_descriptions[0]["entity"]
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
        assert stored.row.content_hash == expected

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

        assert first.row.id == second.row.id
        assert first.row.content_hash == second.row.content_hash
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
                owner_id=2, transcript=transcript.row, body=correction_body()
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
            await repository.append_correction(owner_id=1, transcript=transcript.row, body=body)

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
            owner_id=1, transcript=transcript.row, body=correction_body(reason="misheard_term")
        )
        second = await repository.append_correction(
            owner_id=1,
            transcript=transcript.row,
            body=correction_body(reason="mistranscribed_number"),
        )

        corrections = await repository.corrections(owner_id=1, transcript_id=transcript.row.id)

        assert [correction.id for correction in corrections] == [first.row.id, second.row.id]

    asyncio.run(exercise())


def test_identical_correction_resubmission_replays_instead_of_appending_a_duplicate() -> None:
    """A correction POST that times out is retried on a timer, and the retry
    must not leave a second, identical annotation behind on an append-only
    table. `append_correction` dedupes on the correction body's own content
    hash -- the body already carries `transcript_id`, so that hash is the
    whole identity -- exactly as `store` dedupes a resubmitted transcript.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        body = correction_body()

        first = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )
        second = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )

        assert first.row.id == second.row.id
        assert first.row.content_hash == second.row.content_hash
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 1

    asyncio.run(exercise())


def test_concurrent_identical_corrections_replay_the_same_row_instead_of_duplicating() -> None:
    """The same retry, with the timed-out first request still in flight --
    which is the shape a retry-on-timeout actually has, and the shape a
    dedup SELECT alone cannot survive. Both calls run that SELECT before
    either commits (forced by `race`), both attempt to insert, and
    `uq_speech_transcript_corrections_content` (simulated by
    `FakeSession.flush`) lets only one through. The loser has to recover the
    winner's row as a replay -- not a duplicate, and not the
    `TranscriptUnavailable` every other `IntegrityError` here becomes.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        body = correction_body()
        flushes_before = session.calls.count("flush")
        session.race = _Rendezvous(2)

        first, second = await asyncio.gather(
            repository.append_correction(owner_id=1, transcript=transcript.row, body=body),
            repository.append_correction(owner_id=1, transcript=transcript.row, body=body),
        )

        assert first.row.id == second.row.id
        assert first.row.content_hash == second.row.content_hash
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 1
        # One side inserted and one recovered the winner's row through
        # `_replay_lost_correction`, so exactly one of them is a replay.
        assert {first.replayed, second.replayed} == {False, True}
        # Both calls reached flush. Without the forced interleaving the second
        # would have seen the first row in its own dedup SELECT and returned
        # without inserting, so this pins down that the race was genuinely
        # exercised rather than sidestepped.
        assert session.calls.count("flush") == flushes_before + 2

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

        assert first.row.id == second.row.id
        assert first.row.content_hash == second.row.content_hash
        assert sum(isinstance(row, SpeechTranscript) for row in session.rows) == 1
        # One side inserted and one recovered the winner's row through
        # `_reconcile_lost_race`, so exactly one of them is a replay.
        assert {first.replayed, second.replayed} == {False, True}
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

        winners = [item for item in results if isinstance(item, Written)]
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
    """`append_correction` does have an identity to race on -- the correction
    body's content hash -- but only `IntegrityError` means that race was
    lost. An unexpected `SQLAlchemyError` mid-flush (a dropped connection, a
    statement timeout -- modeled here with `OperationalError`, deliberately
    not `IntegrityError`, to prove the replay recovery isn't reached by
    every database failure) must come out as `TranscriptUnavailable`, with a
    clean exception chain -- never `TranscriptConflict`, which this method
    cannot raise at all, and never a replay of a row that was never written.
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
                owner_id=1, transcript=transcript.row, body=correction_body()
            )
        # The failed attempt left no partial row behind.
        assert sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows) == 0
        # Content-free in the chain too, same guarantee as everywhere else
        # in this file that raises `from None`.
        assert excinfo.value.__suppress_context__ is True

    asyncio.run(exercise())


def test_append_correction_unexplained_integrity_error_surfaces_as_unavailable() -> None:
    """An `IntegrityError` the replay recovery cannot explain -- its re-read
    finds no matching row, so the violation was not the content-hash
    collision it recovers from -- has to surface like every other database
    failure: as `TranscriptUnavailable`, with a clean exception chain, and
    never as `TranscriptConflict`. A content-hash collision has no conflict
    outcome (a differing body is a different identity, not a collision), so
    the only `TranscriptConflict` this method can raise is the capacity one
    covered above -- never a rebadged database failure. This guards against a
    future change "symmetrizing" this method with `store` by borrowing its
    replay-vs-conflict branch, whose conflict half nothing here can produce.
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
                owner_id=1, transcript=transcript.row, body=correction_body()
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


def seed_corrections(
    session: FakeSession, *, owner_id: int, transcript_id: int, count: int
) -> None:
    """Put `count` already-committed corrections on file directly.

    Reaching the cap through `append_correction` itself would canonicalize,
    hash, and flush a thousand bodies, and `FakeSession.flush` rescans every
    row it holds on each insert -- quadratic, and slow enough to matter in a
    unit suite. These rows only ever have to be counted, so they are written
    straight into the fake's list with ids well clear of the ones `flush`
    hands out, which is also what keeps `flush` from trying to assign them one.
    """
    for index in range(count):
        row = SpeechTranscriptCorrection(
            owner_id=owner_id,
            canonical_json=json.dumps({"transcript_id": transcript_id, "seed": index}),
            content_hash=sha256(f"seed-{transcript_id}-{index}".encode()).digest(),
        )
        row.id = 1_000_000 + index
        row.transcript_id = transcript_id
        session.rows.append(row)


def test_append_correction_refuses_a_transcript_already_at_the_correction_cap() -> None:
    """`TranscriptResponse.corrections` declares `MAX_CORRECTIONS_PER_TRANSCRIPT`
    as its maximum length, and nothing used to hold the write path to it. The
    correction past the cap therefore stored fine and then made the transcript
    unrenderable: every later read *and* write went through
    `TranscriptService._to_response`, which built a response model the stored
    rows no longer fit. Refusing the write is what keeps that from happening,
    and `TranscriptConflict` is the shape for it -- the request is well formed
    and its body is within every size limit, it is the transcript's durable
    state that has no room left.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        seed_corrections(
            session,
            owner_id=1,
            transcript_id=transcript.row.id,
            count=MAX_CORRECTIONS_PER_TRANSCRIPT,
        )

        with pytest.raises(TranscriptConflict):
            await repository.append_correction(
                owner_id=1, transcript=transcript.row, body=correction_body()
            )

        stored = sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows)
        assert stored == MAX_CORRECTIONS_PER_TRANSCRIPT

    asyncio.run(exercise())


def test_a_correction_already_on_file_still_replays_at_the_cap() -> None:
    """The cap must not break idempotency. A correction POST is retried on a
    timer, so the retry of the correction that *filled* the transcript has to
    replay the row already written, exactly as it would below the cap -- not
    come back as a conflict telling a client its stored write failed. That is
    why the cap is checked after the content-hash lookup, never before it.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        body = correction_body()
        stored = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )
        seed_corrections(
            session,
            owner_id=1,
            transcript_id=transcript.row.id,
            count=MAX_CORRECTIONS_PER_TRANSCRIPT - 1,
        )

        replayed = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )

        assert replayed.row.id == stored.row.id
        on_file = sum(isinstance(row, SpeechTranscriptCorrection) for row in session.rows)
        assert on_file == MAX_CORRECTIONS_PER_TRANSCRIPT

    asyncio.run(exercise())


def test_the_correction_cap_is_counted_per_transcript() -> None:
    """A transcript that filled its own cap must not close corrections on a
    different transcript. The count is scoped the same way every other query
    in this repository is: by owner and by transcript, never table-wide.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        seed_corrections(
            session,
            owner_id=1,
            transcript_id=transcript.row.id + 1,
            count=MAX_CORRECTIONS_PER_TRANSCRIPT,
        )

        correction = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=correction_body()
        )

        assert correction.row.transcript_id == transcript.row.id

    asyncio.run(exercise())


def test_store_reports_whether_it_inserted_or_replayed() -> None:
    """`store` takes one of two branches and already knows which: an
    existing-row hit with a matching content hash is a replay, a fresh insert
    is not. It reports that alongside the row so its caller does not have to
    re-derive the answer by reading the rows on file before every write.
    """

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

        assert first.replayed is False
        assert second.replayed is True

    asyncio.run(exercise())


def test_append_correction_reports_whether_it_inserted_or_replayed() -> None:
    """The same report on the correction side, and the one that matters most:
    the caller's alternative was reading every correction already on file --
    up to `MAX_CORRECTIONS_PER_TRANSCRIPT` rows of `CORRECTION_BODY_LIMIT`
    bytes each -- to answer this single boolean.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)
        transcript = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )
        body = correction_body()

        first = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )
        second = await repository.append_correction(
            owner_id=1, transcript=transcript.row, body=body
        )

        assert first.replayed is False
        assert second.replayed is True

    asyncio.run(exercise())


def test_by_recording_track_selects_only_the_requested_track() -> None:
    """The track filter has to be part of the SELECT, not a pass over rows the
    query already returned. `system_audio` is stored first here on purpose: a
    lookup that fetched every transcript on the recording and picked in Python
    would still be answering from a list whose first entry is the wrong track.
    """

    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        await repository.store(
            owner_id=1,
            recording=recording,
            track="system_audio",
            body=transcript_body(track="system_audio"),
        )
        stored = await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        found = await repository.by_recording_track(
            owner_id=1, recording_id=42, track="microphone"
        )

        assert found is not None
        assert found.id == stored.row.id
        assert found.track == "microphone"

    asyncio.run(exercise())


def test_by_recording_track_is_owner_scoped_and_reports_a_missing_track_as_none() -> None:
    async def exercise() -> None:
        session = FakeSession()
        repository = SqlAlchemyTranscriptRepository(session)
        recording = SimpleNamespace(id=42)

        await repository.store(
            owner_id=1, recording=recording, track="microphone", body=transcript_body()
        )

        assert (
            await repository.by_recording_track(owner_id=2, recording_id=42, track="microphone")
            is None
        )
        assert (
            await repository.by_recording_track(owner_id=1, recording_id=42, track="system_audio")
            is None
        )
        assert (
            await repository.by_recording_track(owner_id=1, recording_id=43, track="microphone")
            is None
        )

    asyncio.run(exercise())
