"""Owner-scoped durable ingest records for native two-track recordings."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, utc_now

MAX_TRACK_SAMPLES = 48_000 * 120 * 60
MAX_PART_SAMPLES = 48_000 * 60
MAX_PARTS = 120 * 60
MAX_PART_BYTES = MAX_PART_SAMPLES * 2 * 2
MAX_TRACK_BYTES = MAX_TRACK_SAMPLES * 2 * 2

RECORDING_STATES = frozenset(
    {
        "reserved",
        "uploading",
        "sealing",
        "stored",
        "stored_with_gaps",
        "needs_attention",
    }
)
TRACK_STATES = RECORDING_STATES
PART_STATES = frozenset({"reserved", "stored"})
TRACK_KINDS = frozenset({"microphone", "system_audio"})
GAP_REASONS = frozenset(
    {
        "callback_overflow",
        "format_change",
        "route_change",
        "source_discontinuity",
        "missing_audio",
        "corrupt_spool_record",
    }
)

_IDEMPOTENCY_KEY_CHECK = "~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"
_OBJECT_KEY_CHECK = (
    "octet_length({column}) BETWEEN 1 AND 1024 "
    "AND {column} !~ '^/' "
    "AND {column} !~ '(^|/)\\.\\.(/|$)'"
)


class Recording(Base):
    """One native recording aggregate and its durable release gates."""

    __tablename__ = "recordings"
    __table_args__ = (
        UniqueConstraint("owner_id", "id", name="uq_recordings_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "client_recording_id",
            name="uq_recordings_owner_client_recording_id",
        ),
        UniqueConstraint(
            "owner_id",
            "create_idempotency_key",
            name="uq_recordings_owner_create_idempotency",
        ),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint(
            "state IN ('reserved', 'uploading', 'sealing', 'stored', "
            "'stored_with_gaps', 'needs_attention')",
            name="state_allowed",
        ),
        CheckConstraint(
            "coverage_status IS NULL OR coverage_status IN ('complete', 'stored_with_gaps')",
            name="coverage_status_allowed",
        ),
        CheckConstraint(
            "(state = 'stored' AND coverage_status = 'complete') OR "
            "(state = 'stored_with_gaps' AND coverage_status = 'stored_with_gaps') OR "
            "(state NOT IN ('stored', 'stored_with_gaps') AND coverage_status IS NULL)",
            name="state_coverage_coherent",
        ),
        CheckConstraint(
            "audio_created_on_server = (state IN ('stored', 'stored_with_gaps'))",
            name="durable_audio_state_coherent",
        ),
        CheckConstraint(
            "NOT transcript_lineage_accepted OR audio_created_on_server",
            name="transcript_lineage_requires_audio",
        ),
        CheckConstraint(
            "octet_length(create_request_hash) = 32", name="create_request_hash_length"
        ),
        CheckConstraint(
            "create_idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="create_idempotency_key_safe",
        ),
        CheckConstraint(
            "jsonb_typeof(create_result_json) = 'object' "
            "AND octet_length(create_result_json::text) <= 4096",
            name="create_result_json_valid",
        ),
        CheckConstraint(
            "(seal_idempotency_key IS NULL AND seal_request_hash IS NULL "
            "AND seal_result_json IS NULL) OR "
            "(seal_idempotency_key IS NOT NULL AND seal_request_hash IS NOT NULL)",
            name="seal_idempotency_tuple_coherent",
        ),
        CheckConstraint(
            "seal_idempotency_key IS NULL OR seal_idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="seal_idempotency_key_safe",
        ),
        CheckConstraint(
            "seal_request_hash IS NULL OR octet_length(seal_request_hash) = 32",
            name="seal_request_hash_length",
        ),
        CheckConstraint(
            "seal_result_json IS NULL OR (jsonb_typeof(seal_result_json) = 'object' "
            "AND octet_length(seal_result_json::text) <= 8192)",
            name="seal_result_json_valid",
        ),
        CheckConstraint(
            "(state IN ('stored', 'stored_with_gaps') AND seal_result_json IS NOT NULL) "
            "OR (state NOT IN ('stored', 'stored_with_gaps') AND seal_result_json IS NULL)",
            name="seal_result_state_coherent",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_start"),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at", name="sealed_after_creation"
        ),
        Index("ix_recordings_owner_state_created", "owner_id", "state", "created_at", "id"),
        Index(
            "ix_recordings_pending_reconciliation",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text(
                "state IN ('reserved', 'uploading', 'sealing', 'needs_attention')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_recordings_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    client_recording_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    state: Mapped[str] = mapped_column(
        Text, default="reserved", server_default="reserved", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_status: Mapped[str | None] = mapped_column(Text)
    create_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    create_request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    create_result_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    seal_idempotency_key: Mapped[str | None] = mapped_column(Text)
    seal_request_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    seal_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    audio_created_on_server: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    transcript_lineage_accepted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordingTrack(Base):
    """One canonical 48 kHz PCM16 source track within a recording aggregate."""

    __tablename__ = "recording_tracks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_recording_tracks_owner_recording_recordings",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_recording_tracks_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "id",
            name="uq_recording_tracks_owner_recording_id_id",
        ),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "client_track_id",
            name="uq_recording_tracks_owner_recording_client_track_id",
        ),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "kind",
            name="uq_recording_tracks_owner_recording_kind",
        ),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint("kind IN ('microphone', 'system_audio')", name="kind_allowed"),
        CheckConstraint(
            "sample_encoding = 'pcm_s16le' AND sample_rate_hz = 48000 " "AND interleaved",
            name="canonical_pcm16_48khz",
        ),
        CheckConstraint(
            "(kind = 'microphone' AND channel_count = 1) OR "
            "(kind = 'system_audio' AND channel_count = 2)",
            name="kind_channel_count_coherent",
        ),
        CheckConstraint(
            "conversion_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="conversion_version_safe",
        ),
        CheckConstraint(
            "state IN ('reserved', 'uploading', 'sealing', 'stored', "
            "'stored_with_gaps', 'needs_attention')",
            name="state_allowed",
        ),
        CheckConstraint(
            f"high_water_sample BETWEEN 0 AND {MAX_TRACK_SAMPLES}",
            name="high_water_sample_bounded",
        ),
        CheckConstraint(
            f"stored_part_count BETWEEN 0 AND {MAX_PARTS}",
            name="stored_part_count_bounded",
        ),
        CheckConstraint(
            f"stored_byte_length BETWEEN 0 AND {MAX_TRACK_BYTES}",
            name="stored_byte_length_bounded",
        ),
        CheckConstraint(
            "total_sample_count IS NULL OR "
            f"total_sample_count BETWEEN high_water_sample AND {MAX_TRACK_SAMPLES}",
            name="total_sample_count_bounded",
        ),
        CheckConstraint(
            "(state IN ('stored', 'stored_with_gaps') "
            "AND total_sample_count IS NOT NULL AND pcm_sha256 IS NOT NULL "
            "AND timeline_sha256 IS NOT NULL AND manifest_object_key IS NOT NULL "
            "AND manifest_sha256 IS NOT NULL AND manifest_byte_length IS NOT NULL "
            "AND sealed_at IS NOT NULL) OR "
            "(state NOT IN ('stored', 'stored_with_gaps') "
            "AND total_sample_count IS NULL AND pcm_sha256 IS NULL "
            "AND timeline_sha256 IS NULL AND manifest_object_key IS NULL "
            "AND manifest_sha256 IS NULL AND manifest_byte_length IS NULL "
            "AND sealed_at IS NULL)",
            name="final_manifest_state_coherent",
        ),
        CheckConstraint(
            "pcm_sha256 IS NULL OR octet_length(pcm_sha256) = 32",
            name="pcm_sha256_length",
        ),
        CheckConstraint(
            "timeline_sha256 IS NULL OR octet_length(timeline_sha256) = 32",
            name="timeline_sha256_length",
        ),
        CheckConstraint(
            "manifest_sha256 IS NULL OR octet_length(manifest_sha256) = 32",
            name="manifest_sha256_length",
        ),
        CheckConstraint(
            "manifest_byte_length IS NULL OR manifest_byte_length BETWEEN 1 AND 1048576",
            name="manifest_byte_length_bounded",
        ),
        CheckConstraint(
            "manifest_object_key IS NULL OR "
            + _OBJECT_KEY_CHECK.format(column="manifest_object_key"),
            name="manifest_object_key_safe",
        ),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at", name="sealed_after_creation"
        ),
        Index("ix_recording_tracks_owner_recording", "owner_id", "recording_id", "id"),
        Index(
            "ix_recording_tracks_pending_reconciliation",
            "owner_id",
            "state",
            "updated_at",
            "id",
            postgresql_where=text(
                "state IN ('reserved', 'uploading', 'sealing', 'needs_attention')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_recording_tracks_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    recording_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_track_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    sample_encoding: Mapped[str] = mapped_column(
        Text, default="pcm_s16le", server_default="pcm_s16le", nullable=False
    )
    sample_rate_hz: Mapped[int] = mapped_column(
        Integer, default=48_000, server_default="48000", nullable=False
    )
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    interleaved: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    conversion_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        Text, default="reserved", server_default="reserved", nullable=False
    )
    high_water_sample: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    stored_part_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    stored_byte_length: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    total_sample_count: Mapped[int | None] = mapped_column(Integer)
    pcm_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    timeline_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    manifest_object_key: Mapped[str | None] = mapped_column(Text)
    manifest_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    manifest_byte_length: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordingPart(Base):
    """One range-bound PCM part, reserved before immutable object persistence."""

    __tablename__ = "recording_parts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "recording_id", "track_id"],
            [
                "recording_tracks.owner_id",
                "recording_tracks.recording_id",
                "recording_tracks.id",
            ],
            name="fk_recording_parts_owner_recording_track_recording_tracks",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_recording_parts_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "idempotency_key",
            name="uq_recording_parts_owner_recording_track_idempotency",
        ),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sequence",
            name="uq_recording_parts_owner_recording_track_sequence",
        ),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sample_start",
            name="uq_recording_parts_owner_recording_track_sample_start",
        ),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint("state IN ('reserved', 'stored')", name="state_allowed"),
        CheckConstraint(f"sequence BETWEEN 0 AND {MAX_PARTS - 1}", name="sequence_bounded"),
        CheckConstraint(
            f"sample_start BETWEEN 0 AND {MAX_TRACK_SAMPLES - 1}",
            name="sample_start_bounded",
        ),
        CheckConstraint(
            f"sample_count BETWEEN 1 AND {MAX_PART_SAMPLES}",
            name="sample_count_bounded",
        ),
        CheckConstraint(
            f"sample_start + sample_count <= {MAX_TRACK_SAMPLES}",
            name="sample_range_bounded",
        ),
        CheckConstraint(f"byte_length BETWEEN 1 AND {MAX_PART_BYTES}", name="byte_length_bounded"),
        CheckConstraint(
            "ciphertext_byte_length = byte_length + 16", name="ciphertext_length_coherent"
        ),
        CheckConstraint("octet_length(plaintext_sha256) = 32", name="plaintext_sha256_length"),
        CheckConstraint("octet_length(ciphertext_sha256) = 32", name="ciphertext_sha256_length"),
        CheckConstraint("octet_length(request_hash) = 32", name="request_hash_length"),
        CheckConstraint(
            "idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="idempotency_key_safe",
        ),
        CheckConstraint(
            "encryption_version = 'aes-256-gcm-hkdf-sha256-v1'",
            name="encryption_version_supported",
        ),
        CheckConstraint(_OBJECT_KEY_CHECK.format(column="object_key"), name="object_key_safe"),
        CheckConstraint(
            "(state = 'reserved' AND stored_at IS NULL AND result_json IS NULL) OR "
            "(state = 'stored' AND stored_at IS NOT NULL AND result_json IS NOT NULL)",
            name="storage_state_coherent",
        ),
        CheckConstraint(
            "result_json IS NULL OR (jsonb_typeof(result_json) = 'object' "
            "AND octet_length(result_json::text) <= 4096)",
            name="result_json_valid",
        ),
        CheckConstraint(
            "stored_at IS NULL OR stored_at >= created_at", name="stored_after_creation"
        ),
        Index("ix_recording_parts_owner_track_sequence", "owner_id", "track_id", "sequence"),
        Index(
            "ix_recording_parts_reserved_reconciliation",
            "owner_id",
            "created_at",
            "id",
            postgresql_where=text("state = 'reserved'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_recording_parts_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    recording_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    track_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ciphertext_byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plaintext_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    ciphertext_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    encryption_version: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        Text, default="reserved", server_default="reserved", nullable=False
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecordingGap(Base):
    """An explicit non-audio interval; absence is never converted into silence."""

    __tablename__ = "recording_gaps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "recording_id", "track_id"],
            [
                "recording_tracks.owner_id",
                "recording_tracks.recording_id",
                "recording_tracks.id",
            ],
            name="fk_recording_gaps_owner_recording_track_recording_tracks",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_id", "id", name="uq_recording_gaps_owner_id_id"),
        UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sample_start",
            name="uq_recording_gaps_owner_recording_track_sample_start",
        ),
        CheckConstraint("schema_version = 1", name="schema_version_supported"),
        CheckConstraint(
            "reason IN ('callback_overflow', 'format_change', 'route_change', "
            "'source_discontinuity', 'missing_audio', 'corrupt_spool_record')",
            name="reason_allowed",
        ),
        CheckConstraint(
            f"sample_start BETWEEN 0 AND {MAX_TRACK_SAMPLES - 1}",
            name="sample_start_bounded",
        ),
        CheckConstraint(
            f"sample_count BETWEEN 1 AND {MAX_TRACK_SAMPLES}",
            name="sample_count_bounded",
        ),
        CheckConstraint(
            f"sample_start + sample_count <= {MAX_TRACK_SAMPLES}",
            name="sample_range_bounded",
        ),
        Index("ix_recording_gaps_owner_track_start", "owner_id", "track_id", "sample_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("owners.id", name="fk_recording_gaps_owner_id_owners", ondelete="RESTRICT"),
        nullable=False,
    )
    recording_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    track_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    sample_start: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


__all__ = [
    "GAP_REASONS",
    "MAX_PART_BYTES",
    "MAX_PARTS",
    "MAX_PART_SAMPLES",
    "MAX_TRACK_BYTES",
    "MAX_TRACK_SAMPLES",
    "PART_STATES",
    "RECORDING_STATES",
    "TRACK_KINDS",
    "TRACK_STATES",
    "Recording",
    "RecordingGap",
    "RecordingPart",
    "RecordingTrack",
]
