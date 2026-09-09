"""Owner-scoped transcript submission that also flips the spool-release gate.

`Recording.transcript_lineage_accepted` is the flag the macOS client's
`RecordingReleaseGates.mayDeleteLocalSpool` gates on. Setting it is not part of
the transcript repository's job -- `speech.repository` never imports
`recordings.models` for anything but the `Recording` type its callers already
resolved (see that module's docstring) -- so this service does two things the
repository deliberately does not: resolve the path's client-facing recording
UUID to the internal row the repository's `store`/`by_recording` calls need,
and set the flag once a submission succeeds.

Both of those touch `recordings.models.Recording` directly with the shared
request-scoped `AsyncSession`, the same cross-domain import
`speech.repository` already uses for its `recording: Recording` parameter.

Two commits, not one. `SqlAlchemyTranscriptRepository.store` self-commits via
`transaction_scope` (`AsyncSession.begin()` raises if a transaction is already
open, so this service cannot wrap `store` in a further transaction to extend
its commit); flipping the flag is therefore a second, separate commit. Rather
than fight that, `_accept_lineage` runs unconditionally after every
*successful* `store` -- a fresh insert or a content-identical replay alike --
so the sequence is self-healing: if the process dies after `store` commits but
before this second commit, the transcript exists with the flag still false,
and the client's next retry (which lands on the repository's replay path,
since the content is identical) sets it. A submission `store` rejects
(`TranscriptConflict`, `TranscriptTooLarge`, `TranscriptUnavailable`) never
reaches `_accept_lineage` at all.

`recording.id` and `recording.state` are read into locals immediately after
resolving the recording, before any other await -- mirroring
`speech.repository`'s own documented discipline for the same reason: if
`store` loses a race and its `transaction_scope` rolls back, every object in
this session's identity map is expired, `recording` included, and touching its
attributes afterward needs a lazy refresh `AsyncSession` cannot perform
implicitly. `_accept_lineage` re-reads `Recording` fresh by the captured
primary key rather than reusing the (possibly expired) `recording` object.
"""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..recordings.models import Recording
from .contracts import TranscriptConflict, TranscriptNotFound, TranscriptUnavailable
from .models import (
    MAX_CORRECTIONS_PER_TRANSCRIPT,
    SpeechTranscript,
    SpeechTranscriptCorrection,
)
from .repository import SqlAlchemyTranscriptRepository
from .schemas import (
    Track,
    TranscriptCorrectionCommand,
    TranscriptCorrectionResponse,
    TranscriptPage,
    TranscriptResponse,
    TranscriptSubmitCommand,
)


def _correction_response(
    correction: SpeechTranscriptCorrection, *, replayed: bool
) -> TranscriptCorrectionResponse:
    # segment_index/word_start_index/word_end_index/original_text/corrected_text/reason
    # are not their own columns -- only transcript_id is generated. The body's
    # canonical_json, already validated and hashed at write time, is the source.
    body = json.loads(correction.canonical_json)
    return TranscriptCorrectionResponse(
        correction_id=correction.id,
        transcript_id=correction.transcript_id,
        segment_index=body["segment_index"],
        word_start_index=body["word_start_index"],
        word_end_index=body["word_end_index"],
        original_text=body["original_text"],
        corrected_text=body["corrected_text"],
        reason=body["reason"],
        created_at=correction.created_at,
        replayed=replayed,
    )


class TranscriptService:
    """Coordinates owner-scoped transcript persistence and the lineage flag."""

    def __init__(self, session: AsyncSession, repository: SqlAlchemyTranscriptRepository) -> None:
        self._session = session
        self._repository = repository

    async def submit(
        self, *, owner_id: int, recording_id: UUID, command: TranscriptSubmitCommand
    ) -> TranscriptResponse:
        recording = await self._resolve_recording(owner_id=owner_id, recording_id=recording_id)
        recording_pk = recording.id
        if recording.state not in {"stored", "stored_with_gaps"}:
            raise TranscriptConflict()
        stored = await self._repository.store(
            owner_id=owner_id,
            recording=recording,
            track=command.track,
            body=command.model_dump(mode="json"),
        )
        await self._accept_lineage(recording_pk)
        return await self._to_response(
            owner_id=owner_id,
            recording_id=recording_id,
            transcript=stored.row,
            replayed=stored.replayed,
        )

    async def list_for_recording(self, *, owner_id: int, recording_id: UUID) -> TranscriptPage:
        recording = await self._resolve_recording(owner_id=owner_id, recording_id=recording_id)
        transcripts = await self._repository.by_recording(
            owner_id=owner_id, recording_id=recording.id
        )
        return TranscriptPage(
            items=tuple(
                [
                    await self._to_response(
                        owner_id=owner_id,
                        recording_id=recording_id,
                        transcript=transcript,
                        replayed=False,
                    )
                    for transcript in transcripts
                ]
            )
        )

    async def add_correction(
        self,
        *,
        owner_id: int,
        recording_id: UUID,
        track: str,
        command: TranscriptCorrectionCommand,
    ) -> TranscriptCorrectionResponse:
        """Append a correction, reporting whether the repository replayed one.

        `replayed` comes straight from `repository.append_correction`, which
        knows it without being asked: the branch it takes is the answer. A
        retry of a correction the server already stored comes back with
        `replayed` true and the original correction's id, never a second row.

        Deriving it here instead -- by reading the correction ids on file and
        checking whether the appended row is among them -- is what this used
        to do, and it cost a full read of every correction body on the
        transcript, up to `MAX_CORRECTIONS_PER_TRANSCRIPT` of them, on every
        single append.
        """
        recording = await self._resolve_recording(owner_id=owner_id, recording_id=recording_id)
        transcripts = await self._repository.by_recording(
            owner_id=owner_id, recording_id=recording.id
        )
        transcript = next((row for row in transcripts if row.track == track), None)
        if transcript is None:
            raise TranscriptNotFound()
        appended = await self._repository.append_correction(
            owner_id=owner_id, transcript=transcript, body=command.model_dump(mode="json")
        )
        return _correction_response(appended.row, replayed=appended.replayed)

    async def _to_response(
        self, *, owner_id: int, recording_id: UUID, transcript: SpeechTranscript, replayed: bool
    ) -> TranscriptResponse:
        corrections = await self._repository.corrections(
            owner_id=owner_id, transcript_id=transcript.id
        )
        # Bounded here, not only at write time. `repository.append_correction`
        # refuses the correction past the cap, but its count-then-insert guard
        # is not a lock: two appends racing at the boundary can both read the
        # same under-cap count and both insert. That overshoot must not cost
        # the owner the transcript -- every read *and* every resubmission of it
        # builds a `TranscriptResponse` here, and the model's declared
        # `max_length` would turn a handful of extra rows into a permanent
        # `ValidationError` on all of them. The rows themselves are still on
        # file; this only bounds how many of them one response renders.
        return TranscriptResponse(
            transcript_id=transcript.id,
            recording_id=recording_id,
            track=cast(Track, transcript.track),
            content_hash=transcript.content_hash.hex(),
            created_at=transcript.created_at,
            replayed=replayed,
            corrections=tuple(
                _correction_response(correction, replayed=False)
                for correction in corrections[:MAX_CORRECTIONS_PER_TRANSCRIPT]
            ),
        )

    async def _resolve_recording(self, *, owner_id: int, recording_id: UUID) -> Recording:
        try:
            recording = await self._session.scalar(
                select(Recording).where(
                    Recording.owner_id == owner_id,
                    Recording.client_recording_id == recording_id,
                )
            )
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None
        if recording is None:
            raise TranscriptNotFound()
        return recording

    async def _accept_lineage(self, recording_pk: int) -> None:
        try:
            async with transaction_scope(self._session):
                recording = await self._session.scalar(
                    select(Recording).where(Recording.id == recording_pk)
                )
                if recording is None:
                    # RESTRICT foreign keys forbid this row vanishing once a
                    # transcript references it; this is not a real branch.
                    raise TranscriptUnavailable()
                recording.transcript_lineage_accepted = True
                await self._session.flush()
        except SQLAlchemyError:
            raise TranscriptUnavailable() from None


__all__ = ["TranscriptService"]
