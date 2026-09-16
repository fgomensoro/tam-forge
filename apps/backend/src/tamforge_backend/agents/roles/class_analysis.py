"""The English class analysis: fluency, vocabulary, recurring errors, and the trend.

One bounded read per class, from the recording's speaker turns and the speech metrics the
server already measured. The reviewer scores fluency and vocabulary in half points on the
TAM English scale, names recurring errors with a verbatim example each, and compares the
class with the previous ones it is shown. It never claims to have recorded anything.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..runtime import (
    AgentOutputInvalid,
    AgentRuntimeError,
    BoundedClaudeRuntime,
    PreparedAgentRun,
    TransportResult,
)
from ..tools.registry import AgentRole
from .contracts import (
    COMMITTED_ATTEMPT,
    SPEECH_METRICS,
    TASK_BRIEF,
    RoleContractError,
    prepare_role_prompt,
)

CLASS_ANALYSIS_SCHEMA_ID = "urn:tamforge:schema:class-analysis-v1"
CLASS_ANALYSIS_JOB_TYPE = "claude.class_analysis"
CLASS_ANALYSIS_MAX_TURNS = 4
CLASS_ANALYSIS_WALL_TIME_SECONDS = 240.0
CLASS_ANALYSIS_PROMPT_VERSION = "v1"
SCORE_MAXIMUM = Decimal("4")
MAX_TRANSCRIPT_CHARS = 200_000
COMPLETION_MARKERS = ("i marked", "i recorded", "i scheduled", "i completed", "i updated the plan")


class ClassAnalysisUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the class stays unanalysed for now."""


@dataclass(frozen=True, slots=True)
class ClassRecord:
    teacher: str
    starts_at: datetime
    expected_duration_minutes: int
    notes: str


@dataclass(frozen=True, slots=True)
class PreviousClass:
    """What an earlier class scored, so the reviewer compares instead of guessing."""

    starts_at: datetime
    fluency_score: Decimal
    vocabulary_score: Decimal
    recurring_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassAnalysisRequest:
    record: ClassRecord
    transcript: str
    speech_metrics: Mapping[str, object]
    vocabulary_metrics: Mapping[str, object]
    previous: tuple[PreviousClass, ...] = ()
    repair_errors: tuple[str, ...] = ()


class ScoredAspect(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score: Decimal = Field(ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=600)
    evidence: str = Field(min_length=1, max_length=300)


class RecurringError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str = Field(min_length=1, max_length=200)
    example: str = Field(min_length=1, max_length=300)
    correction: str = Field(min_length=1, max_length=300)


class ClassAnalysisOutcome(BaseModel):
    """The only shape a class analysis may take."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fluency: ScoredAspect
    vocabulary: ScoredAspect
    recurring_errors: tuple[RecurringError, ...] = Field(min_length=1, max_length=6)
    progress_direction: Literal["up", "flat", "down", "first_class"]
    progress_statement: str = Field(min_length=1, max_length=600)
    next_focus: str = Field(min_length=1, max_length=400)


class ClassAnalysisTransport(Protocol):
    async def analyse_class(self, request: ClassAnalysisRequest) -> Mapping[str, object]: ...


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def validate_class_analysis(
    payload: Mapping[str, object], *, transcript: str, previous_count: int
) -> tuple[str, ...]:
    """Issues by name; empty means the analysis may be stored."""
    try:
        outcome = ClassAnalysisOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "analysis"
        return (f"analysis {location}: {first['msg']}",)
    haystack = _normalize(transcript)
    for name, aspect in (("fluency", outcome.fluency), ("vocabulary", outcome.vocabulary)):
        if aspect.score != aspect.score.quantize(Decimal("0.5")):
            return (f"{name} must be scored in half points",)
        if _normalize(aspect.evidence) not in haystack:
            return (f"{name} evidence must be a verbatim quote from the transcript",)
    for error in outcome.recurring_errors:
        if _normalize(error.example) not in haystack:
            return ("every recurring error needs a verbatim example from the transcript",)
    if previous_count == 0 and outcome.progress_direction != "first_class":
        return ("with no previous class the progress direction is first_class",)
    if previous_count > 0 and outcome.progress_direction == "first_class":
        return ("there are previous classes to compare with",)
    lowered = " ".join(
        [
            outcome.fluency.rationale,
            outcome.vocabulary.rationale,
            outcome.progress_statement,
            outcome.next_focus,
        ]
    ).lower()
    for marker in COMPLETION_MARKERS:
        if marker in lowered:
            return ("the analysis cannot claim to have recorded, scheduled or completed anything",)
    return ()


@dataclass
class _ClassAnalysisRuntimeAdapter:
    transport: ClassAnalysisTransport
    request: ClassAnalysisRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = ClassAnalysisRequest(
            record=self.request.record,
            transcript=self.request.transcript,
            speech_metrics=self.request.speech_metrics,
            vocabulary_metrics=self.request.vocabulary_metrics,
            previous=self.request.previous,
            repair_errors=repair_errors,
        )
        payload = await self.transport.analyse_class(request)
        return TransportResult(payload=payload, turns=1)


class ClassAnalysisService:
    def __init__(self, transport: ClassAnalysisTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def analyse(self, request: ClassAnalysisRequest) -> ClassAnalysisOutcome:
        """One bounded analysis, or a contract error the caller renders as such."""
        if not request.transcript.strip():
            raise RoleContractError("the class analysis reads a transcript; there is none")
        if len(request.transcript) > MAX_TRANSCRIPT_CHARS:
            raise RoleContractError("the transcript is longer than the analysis may read")
        prepare_role_prompt(
            AgentRole.REVIEWER,
            committed=True,
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SPEECH_METRICS),
        )
        if self._transport is None:
            raise ClassAnalysisUnavailable("the class analysis needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _ClassAnalysisRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_class_analysis(
                payload, transcript=request.transcript, previous_count=len(request.previous)
            ),
        )
        digest = hashlib.sha256(
            f"{request.record.starts_at.isoformat()}:{request.transcript}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"class-analysis:{digest}",
            job_type=CLASS_ANALYSIS_JOB_TYPE,
            model=self._model,
            schema_id=CLASS_ANALYSIS_SCHEMA_ID,
            prompt_version=CLASS_ANALYSIS_PROMPT_VERSION,
            max_turns=CLASS_ANALYSIS_MAX_TURNS,
            wall_time_seconds=CLASS_ANALYSIS_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise ClassAnalysisUnavailable("the analysis did not return a valid outcome") from None
        except AgentRuntimeError as exc:
            raise ClassAnalysisUnavailable(str(exc)) from None
        return ClassAnalysisOutcome.model_validate(result.payload)


def class_analysis_schema() -> dict[str, object]:
    return ClassAnalysisOutcome.model_json_schema()


def vocabulary_metrics(learner_text: str) -> dict[str, object]:
    """Deterministic vocabulary measures of the learner's words: counts, not judgments."""
    words = re.findall(r"[a-z][a-z'-]*", learner_text.casefold())
    unique = set(words)
    long_words = [w for w in unique if len(w) >= 8]
    return {
        "learner_words": len(words),
        "unique_words": len(unique),
        "type_token_ratio": round(len(unique) / len(words), 3) if words else 0.0,
        "long_word_types": len(long_words),
    }


def render_class_analysis_prompt(request: ClassAnalysisRequest) -> str:
    """The prompt the SDK transport sends: the class, the measures, the history, the turns."""
    record = request.record
    lines: list[str] = [
        f"English class with {record.teacher} on {record.starts_at.date().isoformat()}, "
        f"{record.expected_duration_minutes} minutes planned.",
    ]
    if record.notes.strip():
        lines.append("Teacher notes:\n" + record.notes.strip())
    lines.append(
        "Speech metrics measured on the recording:\n"
        + "\n".join(f"- {key}: {value}" for key, value in request.speech_metrics.items())
    )
    lines.append(
        "Vocabulary measures of the learner's words:\n"
        + "\n".join(f"- {key}: {value}" for key, value in request.vocabulary_metrics.items())
    )
    if request.previous:
        lines.append(
            "Previous classes, oldest first (fluency / vocabulary on the 0 to 4 TAM English "
            "scale, and their recurring errors):\n"
            + "\n".join(
                f"- {p.starts_at.date().isoformat()}: fluency {p.fluency_score}, vocabulary "
                f"{p.vocabulary_score}; errors: {', '.join(p.recurring_errors) or 'none'}"
                for p in request.previous
            )
        )
    else:
        lines.append("There is no previous class; progress_direction is first_class.")
    lines.append(
        "Transcript (learner and teacher, timestamps in milliseconds):\n" + request.transcript
    )
    lines.append(
        "Score fluency and vocabulary in half points from 0 to 4 on the TAM English scale, each "
        "with a rationale and a verbatim quote as evidence; list one to six recurring errors, "
        "each with a verbatim example and its correction; state the progress against the "
        "previous classes with a direction; and name one focus for the next class. Never claim "
        "to have recorded, scheduled or completed anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "CLASS_ANALYSIS_JOB_TYPE",
    "CLASS_ANALYSIS_PROMPT_VERSION",
    "CLASS_ANALYSIS_SCHEMA_ID",
    "SCORE_MAXIMUM",
    "ClassAnalysisOutcome",
    "ClassAnalysisRequest",
    "ClassAnalysisService",
    "ClassAnalysisTransport",
    "ClassAnalysisUnavailable",
    "ClassRecord",
    "PreviousClass",
    "RecurringError",
    "ScoredAspect",
    "class_analysis_schema",
    "render_class_analysis_prompt",
    "validate_class_analysis",
    "vocabulary_metrics",
]
