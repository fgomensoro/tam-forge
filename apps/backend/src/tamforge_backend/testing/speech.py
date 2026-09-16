"""Test helpers for speech: a stored recording by hand, and a transcript command."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from ..speech.schemas import TranscriptSubmitCommand


def insert_stored_recording(
    connection: Connection,
    *,
    owner_id: int,
    started_at: datetime,
    english_class_id: int | None = None,
    interview_id: int | None = None,
    activity_id: int | None = None,
) -> UUID:
    """A hand-built `stored` recording that satisfies every coherence check, with its link."""
    client_recording_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO recordings ("
            "owner_id, client_recording_id, state, coverage_status, audio_created_on_server, "
            "started_at, ended_at, english_class_id, interview_id, activity_instance_id, "
            "create_idempotency_key, create_request_hash, create_result_json, "
            "seal_idempotency_key, seal_request_hash, seal_result_json"
            ") VALUES ("
            ":owner_id, :client_recording_id, 'stored', 'complete', true, "
            ":started_at, :ended_at, :class_id, :interview_id, :activity_id, "
            ":create_key, :create_hash, CAST(:create_result AS jsonb), "
            ":seal_key, :seal_hash, CAST(:seal_result AS jsonb)"
            ")"
        ),
        {
            "owner_id": owner_id,
            "client_recording_id": client_recording_id,
            "started_at": started_at,
            "ended_at": started_at + timedelta(seconds=30),
            "class_id": english_class_id,
            "interview_id": interview_id,
            "activity_id": activity_id,
            "create_key": f"create-{uuid4().hex}",
            "create_hash": b"\x00" * 32,
            "create_result": "{}",
            "seal_key": f"seal-{uuid4().hex}",
            "seal_hash": b"\x00" * 32,
            "seal_result": "{}",
        },
    )
    return client_recording_id


def transcript_command(
    *, track: str, segments: list[tuple[int, int, str]]
) -> TranscriptSubmitCommand:
    """A transcript for one track: (start_ms, end_ms, text) segments, one word per token."""
    built: list[dict[str, Any]] = []
    for start, end, sentence in segments:
        tokens = sentence.split()
        step = max((end - start) // max(len(tokens), 1), 1)
        words = [
            {
                "text": token if index == 0 else f" {token}",
                "start_ms": start + index * step,
                "end_ms": min(start + (index + 1) * step, end),
                "probability": 0.9,
            }
            for index, token in enumerate(tokens)
        ]
        built.append({"text": sentence, "start_ms": start, "end_ms": end, "words": words})
    duration = max(end for _, end, _ in segments) / 1000 if segments else 1.0
    return TranscriptSubmitCommand.model_validate(
        {
            "schema_version": 1,
            "track": track,
            "segments": built,
            "model_identity": {
                "runtime_version": "b4938",
                "model_filename": "ggml-small.en-q5_1.bin",
                "model_sha256": "a" * 64,
                "metal_requested": True,
                "used_builtin_vad": False,
                "language": "en",
            },
            "derivation": {
                "derivation_version": "tamforge-asr16k-v1",
                "source_sample_rate": 48_000,
                "source_channel_count": 1,
                "source_sample_count": int(duration * 48_000),
                "output_sample_rate": 16_000,
                "output_sample_count": int(duration * 16_000),
                "zero_filled_gaps": [],
                "source_pcm_sha256": "b" * 64,
                "derived_pcm_sha256": "c" * 64,
                "quality": {
                    "version": "v1",
                    "sample_rate": 48_000,
                    "channel_count": 1,
                    "source_sample_count": int(duration * 48_000),
                    "duration_seconds": duration,
                    "peak_absolute": 12_345,
                    "all_silence": False,
                    "clipped_ratio": 0.0001,
                    "dc_offset": 1e-12,
                    "channel_imbalance_decibels": None,
                    "discontinuity_count": 0,
                    "unavailable_dimensions": [],
                },
            },
        }
    )


__all__ = ["insert_stored_recording", "transcript_command"]
