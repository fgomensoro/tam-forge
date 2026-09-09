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
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from sqlalchemy import select
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
        """
        try:
            canonical = canonical_bytes(
                {**body, "recording_id": recording.id, "track": track},
                limit=TRANSCRIPT_BODY_LIMIT,
            )
        except ValueError:
            raise TranscriptTooLarge() from None
        content_hash = sha256(canonical).digest()

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
        """
        if transcript.owner_id != owner_id:
            raise TranscriptNotFound()
        try:
            canonical = canonical_bytes(
                {**body, "transcript_id": transcript.id}, limit=CORRECTION_BODY_LIMIT
            )
        except ValueError:
            raise TranscriptTooLarge() from None
        content_hash = sha256(canonical).digest()

        async with transaction_scope(self.session):
            row = SpeechTranscriptCorrection(
                owner_id=owner_id,
                canonical_json=canonical.decode("utf-8"),
                content_hash=content_hash,
            )
            self.session.add(row)
            await self.session.flush()
            return _snapshot(row)

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
