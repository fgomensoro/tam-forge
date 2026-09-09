"""Immutable local-transcript provenance and its append-only corrections."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..models.provenance import Record, provenance_checks

TRANSCRIPT_BODY_LIMIT = 4194304
CORRECTION_BODY_LIMIT = 8192
# Corrections are append-only rows, so nothing but this cap bounds how many one
# transcript can accumulate. `repository.append_correction` enforces it at write
# time and `schemas.TranscriptResponse` declares the same number as the maximum
# length of its `corrections` tuple. It lives here rather than in `schemas`
# because both of those layers need it, exactly like the body limits above.
MAX_CORRECTIONS_PER_TRANSCRIPT = 1_000


class SpeechTranscript(Record):
    __tablename__ = "speech_transcripts"
    __table_args__ = provenance_checks(
        "speech_transcripts", limit=TRANSCRIPT_BODY_LIMIT
    ) + (
        UniqueConstraint(
            "owner_id", "recording_id", "track", name="uq_speech_transcripts_recording_track"
        ),
        ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_speech_transcripts_recording",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "track IN ('microphone', 'system_audio')", name="track_allowed"
        ),
    )
    recording_id: Mapped[int] = mapped_column(
        BigInteger,
        Computed("(canonical_json::jsonb->>'recording_id')::bigint", persisted=True),
        nullable=False,
    )
    track: Mapped[str] = mapped_column(
        Text, Computed("canonical_json::jsonb->>'track'", persisted=True), nullable=False
    )


class SpeechTranscriptCorrection(Record):
    __tablename__ = "speech_transcript_corrections"
    __table_args__ = provenance_checks(
        "speech_transcript_corrections", limit=CORRECTION_BODY_LIMIT
    ) + (
        # A correction's identity is its own content: the canonical body already
        # carries `transcript_id`, so two rows with the same content hash under
        # the same transcript are the same annotation submitted twice. This is
        # what makes a client's retry-on-timeout replay instead of appending a
        # duplicate -- see `repository.append_correction`.
        UniqueConstraint(
            "owner_id",
            "transcript_id",
            "content_hash",
            name="uq_speech_transcript_corrections_content",
        ),
        ForeignKeyConstraint(
            ["owner_id", "transcript_id"],
            ["speech_transcripts.owner_id", "speech_transcripts.id"],
            name="fk_speech_transcript_corrections_transcript",
            ondelete="RESTRICT",
        ),
    )
    transcript_id: Mapped[int] = mapped_column(
        BigInteger,
        Computed("(canonical_json::jsonb->>'transcript_id')::bigint", persisted=True),
        nullable=False,
    )


def reject_mutation(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise RuntimeError("speech provenance rows are append-only")


for _model in (SpeechTranscript, SpeechTranscriptCorrection):
    event.listen(_model, "before_update", reject_mutation)
    event.listen(_model, "before_delete", reject_mutation)
