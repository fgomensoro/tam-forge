"""Owner-scoped persistence for immutable transcripts and their corrections.

Public identity for a recording is its client-facing UUID; this repository never
sees it. Callers resolve a `recordings.models.Recording` row (or its bigint `id`)
before calling in here, and every method below works entirely in those internal
ids -- see the repository's own docstring notes on `store` for why.

`store` and `append_correction` each own a full commit via `transaction_scope`,
matching every write method in `agents.prompt_registry`, `agents.model_runs`, and
`recordings.repository`. One consequence: `AsyncSession.begin()` raises if a
transaction is already open, so a caller cannot wrap a call to either of these in
its own `transaction_scope` to extend the same commit -- e.g. `store` finishing
and `Recording.transcript_lineage_accepted` being set can only be two separate
commits, not one. Both operations are individually idempotent (a replayed store
returns the same row; setting an already-true flag is a no-op), so that ordering
is safe to retry, just not atomic in the single-transaction sense.

Both writes additionally have an identity two callers can race on: the client's
own retry-on-timeout, not just theoretical concurrency, per the design doc.
`store`'s identity is `(owner, recording, track)`; `append_correction`'s is the
correction body's own content hash. Taking `store` as the example, both callers
may run their existing-row SELECT before either commits and both see nothing, so
both attempt to insert; the database's `uq_speech_transcripts_recording_track`
constraint lets only one through. Rather than prevent that race with a lock,
`store` lets it happen and recovers from it: the loser's `IntegrityError` --
specifically that type, not `SQLAlchemyError` in general -- is caught and
resolved by re-reading the identity in a fresh transaction and answering the
replay-vs-conflict question its own SELECT would have answered had it run a
moment later. Any other `SQLAlchemyError` (a dropped connection, a statement
timeout hitting the first SELECT, the flush, or the recovery read) is not a
uniqueness collision and is not routed into that recovery at all -- it surfaces
as `TranscriptUnavailable`, a distinct, retryable error, so a transient
infrastructure failure is never mislabeled as the 409-shaped `TranscriptConflict`
a well-behaved client would not retry. No `SQLAlchemyError`, from either the
first attempt or the recovery read, ever reaches the caller untranslated.
`append_correction` recovers its own race the same way, minus the conflict
branch, which content-hash identity makes unreachable there. It has a conflict
of a different kind -- a transcript already holding
`MAX_CORRECTIONS_PER_TRANSCRIPT` corrections has no room for another -- which is
decided before the insert rather than recovered from after it. See its docstring.

`store`'s `recording.id` is read exactly once, into a local, before either
transaction attempt begins. `recording` is the caller's already-loaded ORM
object from this same request-scoped `AsyncSession`; when the first attempt's
`transaction_scope` rolls back on the race above, SQLAlchemy expires every
object in the session's identity map, `recording` included, not only rows the
failed transaction touched. Re-reading `recording.id` after that would need a
lazy refresh an `AsyncSession` cannot perform implicitly outside an awaited ORM
call, and raises `MissingGreenlet` -- itself a `SQLAlchemyError` -- before the
recovery path ever runs. Passing the captured local everywhere instead avoids
touching the expired attribute at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from ..agents.hashing import canonical_bytes
from ..database import transaction_scope
from ..models.provenance import Record
from ..recordings.models import Recording
from .contracts import (
    TranscriptConflict,
    TranscriptNotFound,
    TranscriptTooLarge,
    TranscriptUnavailable,
)
from .models import (
    CORRECTION_BODY_LIMIT,
    MAX_CORRECTIONS_PER_TRANSCRIPT,
    TRANSCRIPT_BODY_LIMIT,
    SpeechTranscript,
    SpeechTranscriptCorrection,
)


def _snapshot[R: Record](row: R) -> R:
    """Detach an independent copy so a later rollback in the same session,
    caused by an unrelated later call, cannot expire the attributes of a row
    already handed back to an earlier caller. Mirrors
    ``agents.models.snapshot_record``; kept local rather than importing across
    domains (matching Task 1's choice not to hoist `reject_mutation` either).
    """
    snapshot = type(row)(
        **{column.key: getattr(row, column.key) for column in row.__table__.columns}
    )
    make_transient_to_detached(snapshot)
    return snapshot


@dataclass(frozen=True, slots=True)
class Written[R: Record]:
    """A written row, plus whether this call replayed it rather than inserting it.

    `store` and `append_correction` each answer two questions at once: which
    row is on file now, and whether this call is the one that put it there.
    Both already know -- an existing-row hit, or either lost-race recovery,
    replays a row an earlier call wrote; a fresh insert does not -- so both
    report it here rather than leaving the caller to re-derive it by reading
    the rows on file before every write. On the correction side that prefetch
    meant pulling up to `MAX_CORRECTIONS_PER_TRANSCRIPT` bodies of
    `CORRECTION_BODY_LIMIT` bytes each out of the database for one boolean.
    """

    row: R
    replayed: bool


def _canonicalize(body: Mapping[str, object], *, limit: int) -> tuple[bytes, bytes]:
    """Canonicalize an already-identity-merged body and hash it.

    Shared by `store` and `append_correction`, which differ only in which
    identity field(s) they merge into `body` before calling this and which
    size limit applies -- kept identical so their size-guard and hashing
    behavior can't drift apart from each other.
    """
    try:
        canonical = canonical_bytes(body, limit=limit)
    except ValueError:
        raise TranscriptTooLarge() from None
    return canonical, sha256(canonical).digest()


class SqlAlchemyTranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def store(
        self,
        *,
        owner_id: int,
        recording: Recording,
        track: str,
        body: Mapping[str, object],
    ) -> Written[SpeechTranscript]:
        """Insert once per (owner, recording, track); replay by content hash.

        `body` is the client's submitted command already dumped to a plain
        mapping. The stored body is not that mapping verbatim: `recording_id`
        (the internal bigint the caller already resolved from the recording's
        public UUID -- resolving that UUID is the caller's job, not this
        repository's) and `track` are merged in first, so the byte-size guard
        below runs against the body that will actually be written, which is
        slightly larger than what the submission schema validated.

        The returned `Written` carries which of the two branches ran, so the
        caller never has to read the transcripts already on file to work out
        whether this submission was a replay.

        See the module docstring for how a race on this identity (two callers
        both seeing no existing row) is resolved without ever surfacing a raw
        database error, and for why `recording.id` is captured once up front
        rather than read again after a possible rollback.
        """
        recording_id = recording.id
        canonical, content_hash = _canonicalize(
            {**body, "recording_id": recording_id, "track": track}, limit=TRANSCRIPT_BODY_LIMIT
        )

        try:
            async with transaction_scope(self.session):
                existing = await self.session.scalar(
                    select(SpeechTranscript).where(
                        SpeechTranscript.owner_id == owner_id,
                        SpeechTranscript.recording_id == recording_id,
                        SpeechTranscript.track == track,
                    )
                )
                if existing is not None:
                    if existing.content_hash != content_hash:
                        raise TranscriptConflict()
                    return Written(_snapshot(existing), replayed=True)
                row = SpeechTranscript(
                    owner_id=owner_id,
                    canonical_json=canonical.decode("utf-8"),
                    content_hash=content_hash,
                )
                self.session.add(row)
                await self.session.flush()
                return Written(_snapshot(row), replayed=False)
        except IntegrityError:
            return Written(
                await self._reconcile_lost_race(
                    owner_id=owner_id,
                    recording_id=recording_id,
                    track=track,
                    content_hash=content_hash,
                ),
                replayed=True,
            )
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None

    async def _reconcile_lost_race(
        self, *, owner_id: int, recording_id: int, track: str, content_hash: bytes
    ) -> SpeechTranscript:
        """Resolve a `store` race lost to another writer's insert.

        Only reached from `store` on a genuine `IntegrityError` -- the
        uniqueness collision the race was built to recover from. This method
        takes `recording_id` as a plain `int`, already resolved by the
        caller; it never touches the `recording` ORM object itself, so it
        cannot re-trigger the expired-attribute failure described in the
        module docstring.

        `transaction_scope`'s own `session.begin()` has already rolled back
        the failed attempt by the time this runs, so it reads fresh, in a
        transaction of its own, and answers the same replay-vs-conflict
        question the original SELECT would have answered had it run a moment
        later: identical content replays the winner's row -- which is why a
        row returned from here is always a replay, and why `store` labels it
        as one -- and anything else (different content, or the identity still
        missing for some other reason) is `TranscriptConflict`, never a raw
        database error. A failure of this re-read itself is not that collision
        either -- it is the same kind of unrelated infrastructure failure
        `store` guards against -- so it also surfaces as
        `TranscriptUnavailable`, not `TranscriptConflict`.
        """
        try:
            async with transaction_scope(self.session):
                existing = await self.session.scalar(
                    select(SpeechTranscript).where(
                        SpeechTranscript.owner_id == owner_id,
                        SpeechTranscript.recording_id == recording_id,
                        SpeechTranscript.track == track,
                    )
                )
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None
        if existing is None or existing.content_hash != content_hash:
            raise TranscriptConflict() from None
        return _snapshot(existing)

    async def by_recording(
        self, *, owner_id: int, recording_id: int
    ) -> tuple[SpeechTranscript, ...]:
        rows = await self.session.scalars(
            select(SpeechTranscript)
            .where(
                SpeechTranscript.owner_id == owner_id,
                SpeechTranscript.recording_id == recording_id,
            )
            .order_by(SpeechTranscript.id)
        )
        return tuple(_snapshot(row) for row in rows.all())

    async def append_correction(
        self,
        *,
        owner_id: int,
        transcript: SpeechTranscript,
        body: Mapping[str, object],
    ) -> Written[SpeechTranscriptCorrection]:
        """Insert once per correction body; replay an identical one by content hash.

        `transcript` must already belong to `owner_id` -- the caller is expected
        to have obtained it from `store` or `by_recording` under that same owner.
        A mismatch reads as not-found rather than forbidden, so a correction
        request cannot be used to confirm another owner's transcript exists.

        Deduplication is the same content-hash mechanism `store` uses, for the
        same reason: the client retries a write on a timer, so a response lost
        to a timeout must replay the row already written rather than append a
        second, identical annotation to an append-only provenance table. The
        canonical body already carries `transcript_id`, so a correction's
        content hash is its whole identity, and
        `uq_speech_transcript_corrections_content` enforces it.

        That makes this an identity two callers race on exactly as `store`'s is:
        a retry whose predecessor is still in flight runs its SELECT before the
        other commits, both attempt to insert, and only one gets through. The
        loser's `IntegrityError` is recovered the same way -- by re-reading the
        identity in a fresh transaction -- and, because content equality *is*
        the identity here, that re-read can only find the row it collided with.
        The collision itself is therefore never a conflict: a correction whose
        body differs is a different identity, not a collision. An
        `IntegrityError` whose re-read finds nothing was some other violation
        entirely, and surfaces like every other `SQLAlchemyError` below: as
        `TranscriptUnavailable`, never `TranscriptConflict`.

        The one conflict this method does raise is capacity.
        `TranscriptResponse` declares room for `MAX_CORRECTIONS_PER_TRANSCRIPT`
        corrections, and nothing else bounds an append-only table, so the
        correction past that cap is refused here -- as `TranscriptConflict`,
        the 409 the corrections route declares, because the request is well
        formed and within every size limit and it is the transcript's durable
        state that has no room left. The check sits *after* the content-hash
        lookup on purpose: a client retries a correction POST on a timer, so the
        retry of the correction that filled the transcript has to replay the row
        already written rather than be told its stored write failed.

        Counting and inserting is not a lock, so two appends racing at the
        boundary can both read the same under-cap count and both insert. That is
        deliberate, matching this repository's approach to every other race here:
        the overshoot is a handful of rows, it costs no correctness on the write
        side, and `TranscriptService._to_response` bounds what it renders so the
        response model cannot overflow either way.

        The returned `Written` carries whether the row was replayed or freshly
        inserted. That is the whole reason it exists: the caller's only other
        way to learn it is to read every correction already on file before
        each append, which at the cap is megabytes of bodies for one boolean.
        """
        if transcript.owner_id != owner_id:
            raise TranscriptNotFound()
        transcript_id = transcript.id
        canonical, content_hash = _canonicalize(
            {**body, "transcript_id": transcript_id}, limit=CORRECTION_BODY_LIMIT
        )

        try:
            async with transaction_scope(self.session):
                existing = await self._correction_by_content(
                    owner_id=owner_id, transcript_id=transcript_id, content_hash=content_hash
                )
                if existing is not None:
                    return Written(_snapshot(existing), replayed=True)
                on_file = await self._correction_count(
                    owner_id=owner_id, transcript_id=transcript_id
                )
                if on_file >= MAX_CORRECTIONS_PER_TRANSCRIPT:
                    raise TranscriptConflict()
                row = SpeechTranscriptCorrection(
                    owner_id=owner_id,
                    canonical_json=canonical.decode("utf-8"),
                    content_hash=content_hash,
                )
                self.session.add(row)
                await self.session.flush()
                return Written(_snapshot(row), replayed=False)
        except IntegrityError:
            return Written(
                await self._replay_lost_correction(
                    owner_id=owner_id, transcript_id=transcript_id, content_hash=content_hash
                ),
                replayed=True,
            )
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None

    async def _correction_count(self, *, owner_id: int, transcript_id: int) -> int:
        total: int | None = await self.session.scalar(
            select(func.count(SpeechTranscriptCorrection.id)).where(
                SpeechTranscriptCorrection.owner_id == owner_id,
                SpeechTranscriptCorrection.transcript_id == transcript_id,
            )
        )
        return total or 0

    async def _correction_by_content(
        self, *, owner_id: int, transcript_id: int, content_hash: bytes
    ) -> SpeechTranscriptCorrection | None:
        existing: SpeechTranscriptCorrection | None = await self.session.scalar(
            select(SpeechTranscriptCorrection).where(
                SpeechTranscriptCorrection.owner_id == owner_id,
                SpeechTranscriptCorrection.transcript_id == transcript_id,
                SpeechTranscriptCorrection.content_hash == content_hash,
            )
        )
        return existing

    async def _replay_lost_correction(
        self, *, owner_id: int, transcript_id: int, content_hash: bytes
    ) -> SpeechTranscriptCorrection:
        """Resolve an `append_correction` insert lost to a concurrent retry.

        `store`'s `_reconcile_lost_race` in miniature, and reached the same
        way: only on a genuine `IntegrityError`. `transaction_scope` has
        already rolled the failed attempt back, so this reads fresh, in a
        transaction of its own, and replays whichever row won -- so a row
        returned from here is always a replay, and `append_correction` labels
        it as one. A re-read that finds nothing means the `IntegrityError` was
        not the uniqueness collision this recovers from, and a re-read that
        fails is the same kind of unrelated infrastructure failure `store`
        guards against; both surface as `TranscriptUnavailable`, never a raw
        database error.
        """
        try:
            async with transaction_scope(self.session):
                existing = await self._correction_by_content(
                    owner_id=owner_id, transcript_id=transcript_id, content_hash=content_hash
                )
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None
        if existing is None:
            raise TranscriptUnavailable() from None
        return _snapshot(existing)

    async def corrections(
        self, *, owner_id: int, transcript_id: int
    ) -> tuple[SpeechTranscriptCorrection, ...]:
        rows = await self.session.scalars(
            select(SpeechTranscriptCorrection)
            .where(
                SpeechTranscriptCorrection.owner_id == owner_id,
                SpeechTranscriptCorrection.transcript_id == transcript_id,
            )
            .order_by(SpeechTranscriptCorrection.id)
        )
        return tuple(_snapshot(row) for row in rows.all())


__all__ = ["SqlAlchemyTranscriptRepository", "Written"]
