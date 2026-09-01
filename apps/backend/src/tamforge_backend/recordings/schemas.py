"""Strict public recording commands, manifests, and status projections."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

SCHEMA_VERSION = 1
SAMPLE_RATE_HZ = 48_000
MAX_RECORDING_SECONDS = 120 * 60
MAX_TRACK_SAMPLES = SAMPLE_RATE_HZ * MAX_RECORDING_SECONDS
MAX_PART_SECONDS = 60
MAX_PART_SAMPLES = SAMPLE_RATE_HZ * MAX_PART_SECONDS
MAX_PARTS = MAX_RECORDING_SECONDS
PCM_BYTES_PER_SAMPLE = 2
AES_GCM_TAG_BYTES = 16
MAX_SOURCE_SAMPLE_RATE_HZ = 384_000
MAX_SOURCE_CHANNEL_COUNT = 32
MAX_PRESENTATION_TIME_VALUE = 9_223_372_036_854_775_807
MAX_PRESENTATION_TIME_TIMESCALE = 1_000_000_000

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
IdempotencyKey = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]
ConversionVersion = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$"),
]
TrackKind = Literal["microphone", "system_audio"]
CoverageStatus = Literal["complete", "stored_with_gaps"]
RecordingState = Literal[
    "reserved",
    "uploading",
    "sealing",
    "stored",
    "stored_with_gaps",
    "needs_attention",
]
GapReason = Literal[
    "callback_overflow",
    "format_change",
    "route_change",
    "source_discontinuity",
    "missing_audio",
    "corrupt_spool_record",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalPCMFormat(StrictModel):
    sample_encoding: Literal["pcm_s16le"] = "pcm_s16le"
    sample_rate_hz: Literal[48_000] = 48_000
    channel_count: Literal[1, 2]
    interleaved: Literal[True] = True


def _validate_track_format(kind: TrackKind, audio_format: CanonicalPCMFormat) -> None:
    expected_channels = 1 if kind == "microphone" else 2
    if audio_format.channel_count != expected_channels:
        raise ValueError(f"{kind} must use {expected_channels} canonical channel(s)")


class RecordingTrackDeclaration(StrictModel):
    track_id: UUID
    kind: TrackKind
    format: CanonicalPCMFormat
    conversion_version: ConversionVersion = "tamforge-pcm16-v1"

    @model_validator(mode="after")
    def validate_format(self) -> Self:
        _validate_track_format(self.kind, self.format)
        return self


class RecordingCreateCommand(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    started_at: datetime
    tracks: Annotated[tuple[RecordingTrackDeclaration, ...], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def validate_tracks(self) -> Self:
        _validate_track_pair(self.tracks)
        _require_utc(self.started_at, "started_at")
        return self


class RecordingCreateResponse(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    state: Literal["reserved", "uploading"]
    replayed: bool


class RecordingPartDescriptor(StrictModel):
    sequence: Annotated[int, Field(ge=0, le=MAX_PARTS - 1)]
    sample_start: Annotated[int, Field(ge=0, lt=MAX_TRACK_SAMPLES)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_PART_SAMPLES)]
    byte_length: Annotated[int, Field(gt=0, le=MAX_PART_SAMPLES * 2 * PCM_BYTES_PER_SAMPLE)]
    plaintext_sha256: Sha256

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.sample_start + self.sample_count > MAX_TRACK_SAMPLES:
            raise ValueError("part range exceeds the recording limit")
        return self


class RecordingGap(StrictModel):
    sample_start: Annotated[int, Field(ge=0, lt=MAX_TRACK_SAMPLES)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_TRACK_SAMPLES)]
    reason: GapReason

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.sample_start + self.sample_count > MAX_TRACK_SAMPLES:
            raise ValueError("gap range exceeds the recording limit")
        return self


class RecordingSourceLineageSegment(StrictModel):
    """One canonical audio range mapped to its captured source provenance."""

    sample_start: Annotated[int, Field(ge=0, lt=MAX_TRACK_SAMPLES)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_TRACK_SAMPLES)]
    source_sample_rate_hz: Annotated[int, Field(gt=0, le=MAX_SOURCE_SAMPLE_RATE_HZ)]
    source_channel_count: Annotated[int, Field(ge=1, le=MAX_SOURCE_CHANNEL_COUNT)]
    device_id: Annotated[str, Field(min_length=1, max_length=256)]
    route: Annotated[str, Field(min_length=1, max_length=256)]
    presentation_time_start: Annotated[int, Field(ge=0, le=MAX_PRESENTATION_TIME_VALUE)]
    presentation_time_end: Annotated[int, Field(ge=0, le=MAX_PRESENTATION_TIME_VALUE)]
    presentation_time_timescale: Annotated[
        int, Field(gt=0, le=MAX_PRESENTATION_TIME_TIMESCALE)
    ]
    conversion_version: ConversionVersion

    @model_validator(mode="after")
    def validate_range_and_presentation_time(self) -> Self:
        if self.sample_start + self.sample_count > MAX_TRACK_SAMPLES:
            raise ValueError("source lineage range exceeds the recording limit")
        if self.presentation_time_end <= self.presentation_time_start:
            raise ValueError("source lineage presentation time must advance")
        return self


class RecordingTrackManifest(StrictModel):
    track_id: UUID
    kind: TrackKind
    format: CanonicalPCMFormat
    total_sample_count: Annotated[int, Field(gt=0, le=MAX_TRACK_SAMPLES)]
    parts: Annotated[tuple[RecordingPartDescriptor, ...], Field(max_length=MAX_PARTS)] = ()
    gaps: Annotated[tuple[RecordingGap, ...], Field(max_length=MAX_PARTS)] = ()
    source_lineage: Annotated[
        tuple[RecordingSourceLineageSegment, ...], Field(max_length=MAX_PARTS)
    ] = ()
    pcm_sha256: Sha256
    timeline_sha256: Sha256
    conversion_version: ConversionVersion

    @model_validator(mode="after")
    def validate_track(self) -> Self:
        _validate_track_format(self.kind, self.format)
        if tuple(part.sequence for part in self.parts) != tuple(range(len(self.parts))):
            raise ValueError("part sequences must be contiguous and ordered from zero")
        for part in self.parts:
            expected_bytes = part.sample_count * self.format.channel_count * PCM_BYTES_PER_SAMPLE
            if part.byte_length != expected_bytes:
                raise ValueError("part byte length does not match canonical PCM range")

        segments = sorted(
            (
                *(
                    (part.sample_start, part.sample_start + part.sample_count)
                    for part in self.parts
                ),
                *((gap.sample_start, gap.sample_start + gap.sample_count) for gap in self.gaps),
            )
        )
        cursor = 0
        for start, end in segments:
            if start != cursor:
                raise ValueError("parts and explicit gaps must cover the timeline exactly once")
            cursor = end
        if cursor != self.total_sample_count:
            raise ValueError("parts and explicit gaps must cover the complete track")
        _validate_source_lineage_coverage(self.parts, self.source_lineage)
        if any(
            segment.conversion_version != self.conversion_version
            for segment in self.source_lineage
        ):
            raise ValueError(
                "source lineage conversion version must match the track conversion version"
            )
        return self


class RecordingSealCommand(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    started_at: datetime
    ended_at: datetime
    coverage_status: CoverageStatus
    tracks: Annotated[tuple[RecordingTrackManifest, ...], Field(min_length=2, max_length=2)]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        _validate_track_pair(self.tracks)
        _require_utc(self.started_at, "started_at")
        _require_utc(self.ended_at, "ended_at")
        if self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        if self.ended_at - self.started_at > timedelta(seconds=MAX_RECORDING_SECONDS):
            raise ValueError("recording elapsed time exceeds the recording limit")
        expected_status: CoverageStatus = (
            "stored_with_gaps" if any(track.gaps for track in self.tracks) else "complete"
        )
        if self.coverage_status != expected_status:
            raise ValueError("coverage status must disclose explicit gaps")
        return self


class RecordingPartUploadMetadata(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    track_id: UUID
    track_kind: TrackKind
    format: CanonicalPCMFormat
    sequence: Annotated[int, Field(ge=0, le=MAX_PARTS - 1)]
    sample_start: Annotated[int, Field(ge=0, lt=MAX_TRACK_SAMPLES)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_PART_SAMPLES)]
    byte_length: Annotated[int, Field(gt=0, le=MAX_PART_SAMPLES * 2 * PCM_BYTES_PER_SAMPLE)]
    ciphertext_byte_length: Annotated[
        int,
        Field(
            gt=AES_GCM_TAG_BYTES,
            le=MAX_PART_SAMPLES * 2 * PCM_BYTES_PER_SAMPLE + AES_GCM_TAG_BYTES,
        ),
    ]
    plaintext_sha256: Sha256
    ciphertext_sha256: Sha256
    nonce_base64url: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{16}$")]
    encryption_version: Literal["aes-256-gcm-hkdf-sha256-v1"]

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        _validate_track_format(self.track_kind, self.format)
        if self.sample_start + self.sample_count > MAX_TRACK_SAMPLES:
            raise ValueError("part range exceeds the recording limit")
        expected_bytes = self.sample_count * self.format.channel_count * PCM_BYTES_PER_SAMPLE
        if self.byte_length != expected_bytes:
            raise ValueError("part byte length does not match canonical PCM range")
        if self.ciphertext_byte_length != self.byte_length + AES_GCM_TAG_BYTES:
            raise ValueError("ciphertext must contain canonical PCM plus one GCM tag")
        return self


class RecordingPartCryptoHeaders(StrictModel):
    part_key_base64url: Annotated[SecretStr, Field(min_length=43, max_length=43)]


class RecordingPartReceipt(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    track_id: UUID
    sequence: Annotated[int, Field(ge=0, le=MAX_PARTS - 1)]
    sample_start: Annotated[int, Field(ge=0, lt=MAX_TRACK_SAMPLES)]
    sample_count: Annotated[int, Field(gt=0, le=MAX_PART_SAMPLES)]
    plaintext_sha256: Sha256
    high_water_sample: Annotated[int, Field(ge=0, le=MAX_TRACK_SAMPLES)]
    replayed: bool


class RecordingTrackStatus(StrictModel):
    track_id: UUID
    kind: TrackKind
    high_water_sample: Annotated[int, Field(ge=0, le=MAX_TRACK_SAMPLES)]
    stored_part_count: Annotated[int, Field(ge=0, le=MAX_PARTS)]
    gap_count: Annotated[int, Field(ge=0, le=MAX_PARTS)]
    manifest_sha256: Sha256 | None = None


class RecordingStatusResponse(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    state: RecordingState
    coverage_status: CoverageStatus | None = None
    tracks: Annotated[tuple[RecordingTrackStatus, ...], Field(min_length=2, max_length=2)]
    audio_created_on_server: bool
    transcript_lineage_accepted: bool

    @model_validator(mode="after")
    def validate_tracks(self) -> Self:
        _validate_track_pair(self.tracks)
        if self.transcript_lineage_accepted and not self.audio_created_on_server:
            raise ValueError("transcript lineage cannot precede durable server audio")
        if self.state in {"reserved", "uploading", "sealing", "needs_attention"}:
            if (
                self.coverage_status is not None
                or self.audio_created_on_server
                or self.transcript_lineage_accepted
            ):
                raise ValueError("nonterminal recording status cannot claim durable audio coverage")
            return self
        expected_coverage: CoverageStatus = (
            "complete" if self.state == "stored" else "stored_with_gaps"
        )
        if self.coverage_status != expected_coverage or not self.audio_created_on_server:
            raise ValueError("stored recording status must agree with durable audio coverage")
        return self


class PendingRecordingPage(StrictModel):
    items: Annotated[tuple[RecordingStatusResponse, ...], Field(max_length=100)]


class RecordingSealResponse(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    recording_id: UUID
    state: Literal["stored", "stored_with_gaps"]
    coverage_status: CoverageStatus
    track_manifest_sha256: Annotated[tuple[Sha256, Sha256], Field(min_length=2, max_length=2)]
    audio_created_on_server: Literal[True] = True
    transcript_lineage_accepted: Literal[False] = False
    replayed: bool

    @model_validator(mode="after")
    def validate_state_coverage(self) -> Self:
        expected_coverage: CoverageStatus = (
            "complete" if self.state == "stored" else "stored_with_gaps"
        )
        if self.coverage_status != expected_coverage:
            raise ValueError("seal response state must agree with coverage status")
        return self


class RecordingProblem(StrictModel):
    type: Annotated[str, Field(min_length=1, max_length=256)]
    title: Annotated[str, Field(min_length=1, max_length=128)]
    status: Annotated[int, Field(ge=400, le=599)]
    detail: Annotated[str, Field(min_length=1, max_length=512)]
    code: Literal[
        "recording_invalid",
        "recording_not_found",
        "recording_conflict",
        "recording_part_invalid",
        "recording_part_conflict",
        "recording_seal_invalid",
        "recording_storage_unavailable",
    ]


def _validate_track_pair(tracks: tuple[object, ...]) -> None:
    if len(tracks) != 2:
        raise ValueError("recording requires exactly two tracks")
    kinds = tuple(getattr(track, "kind") for track in tracks)
    if kinds != ("microphone", "system_audio"):
        raise ValueError("tracks must be ordered microphone then system_audio")
    track_ids = tuple(getattr(track, "track_id") for track in tracks)
    if len(set(track_ids)) != 2:
        raise ValueError("track IDs must be unique")


def _validate_source_lineage_coverage(
    parts: tuple[RecordingPartDescriptor, ...],
    source_lineage: tuple[RecordingSourceLineageSegment, ...],
) -> None:
    audio_ranges = _coalesce_ranges(
        sorted((part.sample_start, part.sample_start + part.sample_count) for part in parts)
    )
    if not audio_ranges:
        if source_lineage:
            raise ValueError("source lineage cannot claim a track without uploaded audio")
        return
    if not source_lineage:
        raise ValueError("source lineage must cover every uploaded audio range")

    range_index = 0
    cursor = audio_ranges[0][0]
    for segment in source_lineage:
        if range_index == len(audio_ranges):
            raise ValueError("source lineage exceeds uploaded audio coverage")
        if segment.sample_start != cursor:
            raise ValueError("source lineage must be ordered and cover uploaded audio exactly once")
        segment_end = segment.sample_start + segment.sample_count
        expected_end = audio_ranges[range_index][1]
        if segment_end > expected_end:
            raise ValueError("source lineage cannot overlap declared gaps or audio ranges")
        cursor = segment_end
        if cursor == expected_end:
            range_index += 1
            if range_index < len(audio_ranges):
                cursor = audio_ranges[range_index][0]
    if range_index != len(audio_ranges):
        raise ValueError("source lineage must cover every uploaded audio range")


def _coalesce_ranges(ranges: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    if not ranges:
        return ()
    coalesced: list[tuple[int, int]] = [ranges[0]]
    for start, end in ranges[1:]:
        previous_start, previous_end = coalesced[-1]
        if start == previous_end:
            coalesced[-1] = (previous_start, end)
        else:
            coalesced.append((start, end))
    return tuple(coalesced)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")


RECORDING_OPENAPI_MODELS: tuple[type[StrictModel], ...] = (
    CanonicalPCMFormat,
    RecordingTrackDeclaration,
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartDescriptor,
    RecordingGap,
    RecordingSourceLineageSegment,
    RecordingTrackManifest,
    RecordingSealCommand,
    RecordingPartUploadMetadata,
    RecordingPartCryptoHeaders,
    RecordingPartReceipt,
    RecordingTrackStatus,
    RecordingStatusResponse,
    PendingRecordingPage,
    RecordingSealResponse,
    RecordingProblem,
)


__all__ = [
    "AES_GCM_TAG_BYTES",
    "ConversionVersion",
    "MAX_PART_SAMPLES",
    "MAX_PRESENTATION_TIME_TIMESCALE",
    "MAX_PRESENTATION_TIME_VALUE",
    "MAX_RECORDING_SECONDS",
    "MAX_SOURCE_CHANNEL_COUNT",
    "MAX_SOURCE_SAMPLE_RATE_HZ",
    "MAX_TRACK_SAMPLES",
    "PCM_BYTES_PER_SAMPLE",
    "RECORDING_OPENAPI_MODELS",
    "CanonicalPCMFormat",
    "CoverageStatus",
    "GapReason",
    "IdempotencyKey",
    "PendingRecordingPage",
    "RecordingCreateCommand",
    "RecordingCreateResponse",
    "RecordingGap",
    "RecordingPartCryptoHeaders",
    "RecordingPartDescriptor",
    "RecordingPartReceipt",
    "RecordingPartUploadMetadata",
    "RecordingProblem",
    "RecordingSealCommand",
    "RecordingSealResponse",
    "RecordingSourceLineageSegment",
    "RecordingState",
    "RecordingStatusResponse",
    "RecordingTrackDeclaration",
    "RecordingTrackManifest",
    "RecordingTrackStatus",
    "SCHEMA_VERSION",
    "SAMPLE_RATE_HZ",
    "Sha256",
    "TrackKind",
]
