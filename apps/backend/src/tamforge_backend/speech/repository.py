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

`store` additionally has an identity two callers can race on: the client's own
retry-on-timeout, not just theoretical concurrency, per the design doc. Both may
run their existing-row SELECT before either commits and both see nothing, so both
attempt to insert; the database's `uq_speech_transcripts_recording_track`
constraint lets only one through. Rather than prevent that race with a lock,
`store` lets it happen and recovers from it: the loser's `IntegrityError` is
caught and resolved by re-reading the identity in a fresh transaction and
answering the replay-vs-conflict question its own SELECT would have answered had
it run a moment later. No `SQLAlchemyError`, from either the first attempt or the
recovery read, ever reaches the caller untranslated.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from ..agents.hashing import canonical_bytes
from ..database import transaction_scope
from ..models.provenance import Record
from ..recordings.models import Recording
from .contracts import TranscriptConflict, TranscriptNotFound, TranscriptTooLarge
from .models import (
    CORRECTION_BODY_LIMIT,
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
    ) -> SpeechTranscript:
        """Insert once per (owner, recording, track); replay by content hash.

        `body` is the client's submitted command already dumped to a plain
        mapping. The stored body is not that mapping verbatim: `recording_id`
        (the internal bigint the caller already resolved from the recording's
        public UUID -- resolving that UUID is the caller's job, not this
        repository's) and `track` are merged in first, so the byte-size guard
        below runs against the body that will actually be written, which is
        slightly larger than what the submission schema validated.

        See the module docstring for how a race on this identity (two callers
        both seeing no existing row) is resolved without ever surfacing a raw
        database error.
        """
        canonical, content_hash = _canonicalize(
            {**body, "recording_id": recording.id, "track": track}, limit=TRANSCRIPT_BODY_LIMIT
        )

        try:
            async with transaction_scope(self.session):
                existing = await self.session.scalar(
                    select(SpeechTranscript).where(
                        SpeechTranscript.owner_id == owner_id,
                        SpeechTranscript.recording_id == recording.id,
                        SpeechTranscript.track == track,
                    )
                )
                if existing is not None:
                    if existing.content_hash != content_hash:
                        raise TranscriptConflict()
                    return _snapshot(existing)
                row = SpeechTranscript(
                    owner_id=owner_id,
                    canonical_json=canonical.decode("utf-8"),
                    content_hash=content_hash,
                )
                self.session.add(row)
                await self.session.flush()
                return _snapshot(row)
        except SQLAlchemyError:
            return await self._reconcile_lost_race(
                owner_id=owner_id, recording_id=recording.id, track=track, content_hash=content_hash
            )

    async def _reconcile_lost_race(
        self, *, owner_id: int, recording_id: int, track: str, content_hash: bytes
    ) -> SpeechTranscript:
        """Resolve a `store` race lost to another writer's insert.

        `transaction_scope`'s own `session.begin()` has already rolled back
        the failed attempt by the time this runs, so it reads fresh, in a
        transaction of its own, and answers the same replay-vs-conflict
        question the original SELECT would have answered had it run a moment
        later: identical content replays the winner's row, anything else
        (different content, or the identity still missing for some other
        reason) is `TranscriptConflict` -- never a raw database error.
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
            raise TranscriptConflict() from None
        if existing is None or existing.content_hash != content_hash:
            raise TranscriptConflict()
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
    ) -> SpeechTranscriptCorrection:
        """Append a correction to `transcript`; corrections are never deduplicated.

        `transcript` must already belong to `owner_id` -- the caller is expected
        to have obtained it from `store` or `by_recording` under that same owner.
        A mismatch reads as not-found rather than forbidden, so a correction
        request cannot be used to confirm another owner's transcript exists.

        Unlike `store`, there is no identity to race on here -- corrections
        are always inserted, never deduplicated -- so there is nothing to
        retry. The `except` below exists only so an unexpected
        `SQLAlchemyError` (a dropped connection, a statement timeout) still
        reaches the caller as `TranscriptConflict` rather than raw.
        """
        if transcript.owner_id != owner_id:
            raise TranscriptNotFound()
        canonical, content_hash = _canonicalize(
            {**body, "transcript_id": transcript.id}, limit=CORRECTION_BODY_LIMIT
        )

        try:
            async with transaction_scope(self.session):
                row = SpeechTranscriptCorrection(
                    owner_id=owner_id,
                    canonical_json=canonical.decode("utf-8"),
                    content_hash=content_hash,
                )
                self.session.add(row)
                await self.session.flush()
                return _snapshot(row)
        except SQLAlchemyError:
            raise TranscriptConflict() from None

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


__all__ = ["SqlAlchemyTranscriptRepository"]
