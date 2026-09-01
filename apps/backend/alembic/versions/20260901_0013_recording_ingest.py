"""Add owner-scoped durable native recording ingest tables.

Revision ID: 20260901_0013_recording_ingest
Revises: 20260828_0012_native_auth
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0013_recording_ingest"
down_revision: str | None = "20260828_0012_native_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_TRACK_SAMPLES = 48_000 * 120 * 60
MAX_PART_SAMPLES = 48_000 * 60
MAX_PARTS = 120 * 60
MAX_PART_BYTES = MAX_PART_SAMPLES * 2 * 2
MAX_TRACK_BYTES = MAX_TRACK_SAMPLES * 2 * 2

_IDEMPOTENCY_KEY_CHECK = "~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'"


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False)


def _created() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def _updated() -> sa.Column[object]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def _object_key_check(column: str) -> str:
    return (
        f"octet_length({column}) BETWEEN 1 AND 1024 "
        f"AND {column} !~ '^/' "
        f"AND {column} !~ '(^|/)\\.\\.(/|$)'"
    )


def upgrade() -> None:
    op.create_table(
        "recordings",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("client_recording_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("state", sa.Text(), server_default="reserved", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_status", sa.Text(), nullable=True),
        sa.Column("create_idempotency_key", sa.Text(), nullable=False),
        sa.Column("create_request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "create_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("seal_idempotency_key", sa.Text(), nullable=True),
        sa.Column("seal_request_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column(
            "seal_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "audio_created_on_server",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "transcript_lineage_accepted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        _created(),
        _updated(),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("schema_version = 1", name="schema_version_supported"),
        sa.CheckConstraint(
            "state IN ('reserved', 'uploading', 'sealing', 'stored', "
            "'stored_with_gaps', 'needs_attention')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            "coverage_status IS NULL OR coverage_status IN ('complete', 'stored_with_gaps')",
            name="coverage_status_allowed",
        ),
        sa.CheckConstraint(
            "(state = 'stored' AND coverage_status = 'complete') OR "
            "(state = 'stored_with_gaps' AND coverage_status = 'stored_with_gaps') OR "
            "(state NOT IN ('stored', 'stored_with_gaps') AND coverage_status IS NULL)",
            name="state_coverage_coherent",
        ),
        sa.CheckConstraint(
            "audio_created_on_server = (state IN ('stored', 'stored_with_gaps'))",
            name="durable_audio_state_coherent",
        ),
        sa.CheckConstraint(
            "NOT transcript_lineage_accepted OR audio_created_on_server",
            name="transcript_lineage_requires_audio",
        ),
        sa.CheckConstraint(
            "octet_length(create_request_hash) = 32", name="create_request_hash_length"
        ),
        sa.CheckConstraint(
            "create_idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="create_idempotency_key_safe",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(create_result_json) = 'object' "
            "AND octet_length(create_result_json::text) <= 4096",
            name="create_result_json_valid",
        ),
        sa.CheckConstraint(
            "(seal_idempotency_key IS NULL AND seal_request_hash IS NULL "
            "AND seal_result_json IS NULL) OR "
            "(seal_idempotency_key IS NOT NULL AND seal_request_hash IS NOT NULL)",
            name="seal_idempotency_tuple_coherent",
        ),
        sa.CheckConstraint(
            "seal_idempotency_key IS NULL OR seal_idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="seal_idempotency_key_safe",
        ),
        sa.CheckConstraint(
            "seal_request_hash IS NULL OR octet_length(seal_request_hash) = 32",
            name="seal_request_hash_length",
        ),
        sa.CheckConstraint(
            "seal_result_json IS NULL OR (jsonb_typeof(seal_result_json) = 'object' "
            "AND octet_length(seal_result_json::text) <= 8192)",
            name="seal_result_json_valid",
        ),
        sa.CheckConstraint(
            "(state IN ('stored', 'stored_with_gaps') AND seal_result_json IS NOT NULL) "
            "OR (state NOT IN ('stored', 'stored_with_gaps') AND seal_result_json IS NULL)",
            name="seal_result_state_coherent",
        ),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_start"),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at", name="sealed_after_creation"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_recordings_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recordings"),
        sa.UniqueConstraint("owner_id", "id", name="uq_recordings_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "client_recording_id",
            name="uq_recordings_owner_client_recording_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "create_idempotency_key",
            name="uq_recordings_owner_create_idempotency",
        ),
    )
    op.create_index(
        "ix_recordings_owner_state_created",
        "recordings",
        ["owner_id", "state", "created_at", "id"],
    )
    op.create_index(
        "ix_recordings_pending_reconciliation",
        "recordings",
        ["owner_id", "created_at", "id"],
        postgresql_where=sa.text(
            "state IN ('reserved', 'uploading', 'sealing', 'needs_attention')"
        ),
    )

    op.create_table(
        "recording_tracks",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("client_track_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sample_encoding", sa.Text(), server_default="pcm_s16le", nullable=False),
        sa.Column("sample_rate_hz", sa.Integer(), server_default="48000", nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("interleaved", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("conversion_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="reserved", nullable=False),
        sa.Column("high_water_sample", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stored_part_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stored_byte_length", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_sample_count", sa.Integer(), nullable=True),
        sa.Column("pcm_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.Column("timeline_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.Column("manifest_object_key", sa.Text(), nullable=True),
        sa.Column("manifest_sha256", sa.LargeBinary(length=32), nullable=True),
        sa.Column("manifest_byte_length", sa.BigInteger(), nullable=True),
        _created(),
        _updated(),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("schema_version = 1", name="schema_version_supported"),
        sa.CheckConstraint("kind IN ('microphone', 'system_audio')", name="kind_allowed"),
        sa.CheckConstraint(
            "sample_encoding = 'pcm_s16le' AND sample_rate_hz = 48000 " "AND interleaved",
            name="canonical_pcm16_48khz",
        ),
        sa.CheckConstraint(
            "(kind = 'microphone' AND channel_count = 1) OR "
            "(kind = 'system_audio' AND channel_count = 2)",
            name="kind_channel_count_coherent",
        ),
        sa.CheckConstraint(
            "conversion_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="conversion_version_safe",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'uploading', 'sealing', 'stored', "
            "'stored_with_gaps', 'needs_attention')",
            name="state_allowed",
        ),
        sa.CheckConstraint(
            f"high_water_sample BETWEEN 0 AND {MAX_TRACK_SAMPLES}",
            name="high_water_sample_bounded",
        ),
        sa.CheckConstraint(
            f"stored_part_count BETWEEN 0 AND {MAX_PARTS}",
            name="stored_part_count_bounded",
        ),
        sa.CheckConstraint(
            f"stored_byte_length BETWEEN 0 AND {MAX_TRACK_BYTES}",
            name="stored_byte_length_bounded",
        ),
        sa.CheckConstraint(
            "total_sample_count IS NULL OR "
            f"total_sample_count BETWEEN high_water_sample AND {MAX_TRACK_SAMPLES}",
            name="total_sample_count_bounded",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "pcm_sha256 IS NULL OR octet_length(pcm_sha256) = 32",
            name="pcm_sha256_length",
        ),
        sa.CheckConstraint(
            "timeline_sha256 IS NULL OR octet_length(timeline_sha256) = 32",
            name="timeline_sha256_length",
        ),
        sa.CheckConstraint(
            "manifest_sha256 IS NULL OR octet_length(manifest_sha256) = 32",
            name="manifest_sha256_length",
        ),
        sa.CheckConstraint(
            "manifest_byte_length IS NULL OR manifest_byte_length BETWEEN 1 AND 1048576",
            name="manifest_byte_length_bounded",
        ),
        sa.CheckConstraint(
            "manifest_object_key IS NULL OR " + _object_key_check("manifest_object_key"),
            name="manifest_object_key_safe",
        ),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at", name="sealed_after_creation"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_recording_tracks_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "recording_id"],
            ["recordings.owner_id", "recordings.id"],
            name="fk_recording_tracks_owner_recording_recordings",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_tracks"),
        sa.UniqueConstraint("owner_id", "id", name="uq_recording_tracks_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "id",
            name="uq_recording_tracks_owner_recording_id_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "client_track_id",
            name="uq_recording_tracks_owner_recording_client_track_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "kind",
            name="uq_recording_tracks_owner_recording_kind",
        ),
    )
    op.create_index(
        "ix_recording_tracks_owner_recording",
        "recording_tracks",
        ["owner_id", "recording_id", "id"],
    )
    op.create_index(
        "ix_recording_tracks_pending_reconciliation",
        "recording_tracks",
        ["owner_id", "state", "updated_at", "id"],
        postgresql_where=sa.text(
            "state IN ('reserved', 'uploading', 'sealing', 'needs_attention')"
        ),
    )

    op.create_table(
        "recording_parts",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sample_start", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("ciphertext_byte_length", sa.BigInteger(), nullable=False),
        sa.Column("plaintext_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("ciphertext_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("encryption_version", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), server_default="reserved", nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _created(),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("schema_version = 1", name="schema_version_supported"),
        sa.CheckConstraint("state IN ('reserved', 'stored')", name="state_allowed"),
        sa.CheckConstraint(f"sequence BETWEEN 0 AND {MAX_PARTS - 1}", name="sequence_bounded"),
        sa.CheckConstraint(
            f"sample_start BETWEEN 0 AND {MAX_TRACK_SAMPLES - 1}",
            name="sample_start_bounded",
        ),
        sa.CheckConstraint(
            f"sample_count BETWEEN 1 AND {MAX_PART_SAMPLES}",
            name="sample_count_bounded",
        ),
        sa.CheckConstraint(
            f"sample_start + sample_count <= {MAX_TRACK_SAMPLES}",
            name="sample_range_bounded",
        ),
        sa.CheckConstraint(
            f"byte_length BETWEEN 1 AND {MAX_PART_BYTES}", name="byte_length_bounded"
        ),
        sa.CheckConstraint(
            "ciphertext_byte_length = byte_length + 16", name="ciphertext_length_coherent"
        ),
        sa.CheckConstraint("octet_length(plaintext_sha256) = 32", name="plaintext_sha256_length"),
        sa.CheckConstraint("octet_length(ciphertext_sha256) = 32", name="ciphertext_sha256_length"),
        sa.CheckConstraint("octet_length(request_hash) = 32", name="request_hash_length"),
        sa.CheckConstraint(
            "idempotency_key " + _IDEMPOTENCY_KEY_CHECK,
            name="idempotency_key_safe",
        ),
        sa.CheckConstraint(
            "encryption_version = 'aes-256-gcm-hkdf-sha256-v1'",
            name="encryption_version_supported",
        ),
        sa.CheckConstraint(_object_key_check("object_key"), name="object_key_safe"),
        sa.CheckConstraint(
            "(state = 'reserved' AND stored_at IS NULL AND result_json IS NULL) OR "
            "(state = 'stored' AND stored_at IS NOT NULL AND result_json IS NOT NULL)",
            name="storage_state_coherent",
        ),
        sa.CheckConstraint(
            "result_json IS NULL OR (jsonb_typeof(result_json) = 'object' "
            "AND octet_length(result_json::text) <= 4096)",
            name="result_json_valid",
        ),
        sa.CheckConstraint(
            "stored_at IS NULL OR stored_at >= created_at", name="stored_after_creation"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_recording_parts_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "recording_id", "track_id"],
            [
                "recording_tracks.owner_id",
                "recording_tracks.recording_id",
                "recording_tracks.id",
            ],
            name="fk_recording_parts_owner_recording_track_recording_tracks",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_parts"),
        sa.UniqueConstraint("owner_id", "id", name="uq_recording_parts_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "idempotency_key",
            name="uq_recording_parts_owner_recording_track_idempotency",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sequence",
            name="uq_recording_parts_owner_recording_track_sequence",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sample_start",
            name="uq_recording_parts_owner_recording_track_sample_start",
        ),
    )
    op.create_index(
        "ix_recording_parts_owner_track_sequence",
        "recording_parts",
        ["owner_id", "track_id", "sequence"],
    )
    op.create_index(
        "ix_recording_parts_reserved_reconciliation",
        "recording_parts",
        ["owner_id", "created_at", "id"],
        postgresql_where=sa.text("state = 'reserved'"),
    )

    op.create_table(
        "recording_gaps",
        _id(),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("recording_id", sa.BigInteger(), nullable=False),
        sa.Column("track_id", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sample_start", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint("schema_version = 1", name="schema_version_supported"),
        sa.CheckConstraint(
            "reason IN ('callback_overflow', 'format_change', 'route_change', "
            "'source_discontinuity', 'missing_audio', 'corrupt_spool_record')",
            name="reason_allowed",
        ),
        sa.CheckConstraint(
            f"sample_start BETWEEN 0 AND {MAX_TRACK_SAMPLES - 1}",
            name="sample_start_bounded",
        ),
        sa.CheckConstraint(
            f"sample_count BETWEEN 1 AND {MAX_TRACK_SAMPLES}",
            name="sample_count_bounded",
        ),
        sa.CheckConstraint(
            f"sample_start + sample_count <= {MAX_TRACK_SAMPLES}",
            name="sample_range_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name="fk_recording_gaps_owner_id_owners",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "recording_id", "track_id"],
            [
                "recording_tracks.owner_id",
                "recording_tracks.recording_id",
                "recording_tracks.id",
            ],
            name="fk_recording_gaps_owner_recording_track_recording_tracks",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recording_gaps"),
        sa.UniqueConstraint("owner_id", "id", name="uq_recording_gaps_owner_id_id"),
        sa.UniqueConstraint(
            "owner_id",
            "recording_id",
            "track_id",
            "sample_start",
            name="uq_recording_gaps_owner_recording_track_sample_start",
        ),
    )
    op.create_index(
        "ix_recording_gaps_owner_track_start",
        "recording_gaps",
        ["owner_id", "track_id", "sample_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_recording_gaps_owner_track_start", table_name="recording_gaps")
    op.drop_table("recording_gaps")
    op.drop_index("ix_recording_parts_reserved_reconciliation", table_name="recording_parts")
    op.drop_index("ix_recording_parts_owner_track_sequence", table_name="recording_parts")
    op.drop_table("recording_parts")
    op.drop_index("ix_recording_tracks_pending_reconciliation", table_name="recording_tracks")
    op.drop_index("ix_recording_tracks_owner_recording", table_name="recording_tracks")
    op.drop_table("recording_tracks")
    op.drop_index("ix_recordings_pending_reconciliation", table_name="recordings")
    op.drop_index("ix_recordings_owner_state_created", table_name="recordings")
    op.drop_table("recordings")
