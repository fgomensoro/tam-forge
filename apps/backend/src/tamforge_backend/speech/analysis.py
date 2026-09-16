"""The speech analysis of one recording: speaker turns with timestamps, plus the metrics.

The Mac transcribes each track on-device and submits one transcript per track. The two
tracks share one clock, so the turns are the two segment lists interleaved by start time,
labelled `learner` (microphone) and `other` (system audio), with consecutive segments of
the same speaker merged. The worker computes this once per submitted transcript and
stores it; the app reads it back in a readable form. Nothing here is a judgement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import JobResponse
from ..jobs.service import JobService
from ..models.base import utc_now
from ..notifications.models import BackgroundJob
from ..recordings.models import Recording
from .jobs import SPEECH_ANALYSIS_KIND, ProcessingStatus, enqueue_speech_analysis
from .metrics.models import MeasuredMetric, Metric
from .metrics.service import TranscriptSource, calculate_speech_metrics
from .models import SpeechAnalysis, SpeechTranscript
from .schemas import (
    SpeechAnalysisResponse,
    SpeechTurnResponse,
    TranscriptSubmitCommand,
)

ANALYSIS_VERSION: Final = "speech-analysis-v1"
Speaker = Literal["learner", "other"]
MERGE_GAP_MS: Final = 1500


class SpeechAnalysisError(Exception):
    """The analysis could not be produced from what is stored."""


class SpeechAnalysisInvalid(SpeechAnalysisError):
    """The stored transcripts cannot be analysed; retrying will not help."""


@dataclass(frozen=True, slots=True)
class Turn:
    speaker: Speaker
    start_ms: int
    end_ms: int
    text: str

    def as_json(self) -> dict[str, object]:
        return {
            "speaker": self.speaker,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
        }


def build_turns(
    microphone: TranscriptSubmitCommand, system_audio: TranscriptSubmitCommand | None
) -> tuple[Turn, ...]:
    """Interleave both tracks by start time and merge runs of the same speaker."""
    pieces: list[tuple[int, int, Speaker, str]] = [
        (segment.start_ms, segment.end_ms, "learner", segment.text.strip())
        for segment in microphone.segments
        if segment.text.strip()
    ]
    if system_audio is not None:
        pieces.extend(
            (segment.start_ms, segment.end_ms, "other", segment.text.strip())
            for segment in system_audio.segments
            if segment.text.strip()
        )
    pieces.sort(key=lambda item: (item[0], item[1]))
    turns: list[Turn] = []
    for start, end, speaker, text in pieces:
        last = turns[-1] if turns else None
        if last is not None and last.speaker == speaker and start - last.end_ms <= MERGE_GAP_MS:
            turns[-1] = Turn(speaker, last.start_ms, max(last.end_ms, end), f"{last.text} {text}")
        else:
            turns.append(Turn(speaker, start, end, text))
    return tuple(turns)


def metrics_json(report: Any) -> dict[str, object]:
    """Every metric by name: a number when measured, the reason code when not."""
    values: dict[str, object] = {}
    for name in (
        "response_duration_seconds",
        "speech_rate_wpm",
        "articulation_rate_wpm",
        "phonation_time_ratio",
        "mean_length_of_run",
        "pause_count_250_499_ms",
        "pause_count_500_999_ms",
        "pause_count_1000_ms_plus",
        "pause_seconds_total",
        "filler_count",
        "restart_count",
        "response_latency_ms",
    ):
        metric: Metric = getattr(report, name)
        if isinstance(metric, MeasuredMetric):
            value = metric.value
            values[name] = int(value) if value == value.to_integral_value() else float(value)
        else:
            values[name] = {"unavailable": metric.reason_code}
    return values


class SpeechAnalysisService:
    """Enqueue on submit, process from the worker, read for the app."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, *, owner_id: int, recording_pk: int, transcript_id: int) -> JobResponse:
        # The enqueue replays by request hash, so `available_at` must be stable across a
        # resubmission of the same transcript: the transcript's own creation time is.
        created_at = await self._session.scalar(
            select(SpeechTranscript.created_at).where(SpeechTranscript.id == transcript_id)
        )
        await self._session.rollback()
        job, _ = await enqueue_speech_analysis(
            JobService(SqlAlchemyJobRepository(self._session)),
            owner_id=owner_id,
            recording_id=recording_pk,
            transcript_id=transcript_id,
            available_at=created_at or utc_now(),
        )
        return job

    async def process(self, *, owner_id: int, recording_pk: int) -> SpeechAnalysis:
        """Compute turns and metrics from the stored transcripts and upsert the analysis."""
        async with transaction_scope(self._session):
            rows = (
                await self._session.scalars(
                    select(SpeechTranscript)
                    .where(SpeechTranscript.owner_id == owner_id)
                    .where(SpeechTranscript.recording_id == recording_pk)
                    .order_by(SpeechTranscript.id)
                )
            ).all()
            by_track = {row.track: row for row in rows}
            microphone = by_track.get("microphone")
            if microphone is None:
                raise SpeechAnalysisInvalid("the microphone transcript is not stored")
            recording = await self._session.scalar(
                select(Recording.client_recording_id).where(Recording.id == recording_pk)
            )
            if recording is None:
                raise SpeechAnalysisInvalid("the recording is not stored")
            try:
                microphone_command = _command(microphone)
                system = by_track.get("system_audio")
                system_command = None if system is None else _command(system)
                report = calculate_speech_metrics(
                    recording_id=recording,
                    microphone=TranscriptSource(
                        microphone.id, microphone.content_hash.hex(), microphone_command
                    ),
                    system_audio=(
                        None
                        if system is None or system_command is None
                        else TranscriptSource(system.id, system.content_hash.hex(), system_command)
                    ),
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise SpeechAnalysisInvalid(str(exc)) from None
            turns = build_turns(microphone_command, system_command)
            analysis = await self._session.scalar(
                select(SpeechAnalysis)
                .where(SpeechAnalysis.owner_id == owner_id)
                .where(SpeechAnalysis.recording_id == recording_pk)
                .with_for_update()
            )
            now = utc_now()
            if analysis is None:
                analysis = SpeechAnalysis(
                    owner_id=owner_id,
                    recording_id=recording_pk,
                    microphone_transcript_id=microphone.id,
                    system_audio_transcript_id=None if system is None else system.id,
                    analysis_version=ANALYSIS_VERSION,
                )
                self._session.add(analysis)
            analysis.microphone_transcript_id = microphone.id
            analysis.system_audio_transcript_id = None if system is None else system.id
            analysis.analysis_version = ANALYSIS_VERSION
            analysis.turns = [turn.as_json() for turn in turns]
            analysis.metrics = metrics_json(report)
            analysis.updated_at = now
            await self._session.flush()
            return analysis

    async def read(self, *, owner_id: int, recording_pk: int) -> SpeechAnalysisResponse:
        """The stored analysis plus the queue's view of it; never a raw database error."""
        try:
            analysis = await self._session.scalar(
                select(SpeechAnalysis)
                .where(SpeechAnalysis.owner_id == owner_id)
                .where(SpeechAnalysis.recording_id == recording_pk)
            )
            latest_job = await self._session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.owner_id == owner_id)
                .where(BackgroundJob.kind == SPEECH_ANALYSIS_KIND)
                .where(BackgroundJob.payload["subject_id"].as_integer() == recording_pk)
                .order_by(BackgroundJob.id.desc())
                .limit(1)
            )
            response = _response(analysis, latest_job)
            await self._session.rollback()
            return response
        except SQLAlchemyError:
            raise SpeechAnalysisError("the speech analysis store is unavailable") from None


def _command(row: SpeechTranscript) -> TranscriptSubmitCommand:
    # The stored body carries the recording id the repository added; the command forbids it.
    payload = {
        key: value
        for key, value in json.loads(row.canonical_json).items()
        if key in TranscriptSubmitCommand.model_fields
    }
    return TranscriptSubmitCommand.model_validate(payload)


def _status_from_job(job: BackgroundJob | None) -> ProcessingStatus | Literal["not_requested"]:
    if job is None:
        return "not_requested"
    if job.state == "queued":
        return "queued"
    if job.state == "running":
        return "running"
    if job.state == "succeeded":
        return "published"
    if job.state == "canceled":
        return "canceled"
    return "needs_attention"


def _response(analysis: SpeechAnalysis | None, job: BackgroundJob | None) -> SpeechAnalysisResponse:
    status = _status_from_job(job)
    failure = job.last_error_category if job is not None and status == "needs_attention" else None
    if analysis is not None and status in {"not_requested", "published"}:
        status = "published"
    return SpeechAnalysisResponse(
        status=status,
        failure_category=cast(Any, failure),
        analysis_version=None if analysis is None else analysis.analysis_version,
        turns=tuple(
            SpeechTurnResponse(
                speaker=cast(Any, turn["speaker"]),
                start_ms=int(cast(Any, turn["start_ms"])),
                end_ms=int(cast(Any, turn["end_ms"])),
                text=str(turn["text"]),
            )
            for turn in (analysis.turns if analysis is not None else [])
        ),
        metrics=dict(analysis.metrics) if analysis is not None else {},
        updated_at=None if analysis is None else analysis.updated_at,
    )


__all__ = [
    "ANALYSIS_VERSION",
    "SpeechAnalysisError",
    "SpeechAnalysisInvalid",
    "SpeechAnalysisService",
    "Turn",
    "build_turns",
    "metrics_json",
]
