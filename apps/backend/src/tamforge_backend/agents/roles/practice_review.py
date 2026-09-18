"""The review of one free-practice interview answer.

The learner answered one question of their own answer bank aloud, uninterrupted, and the
recording was transcribed. One bounded read scores that answer on the interview tracker's
three single-answer dimensions in half points, each with a verbatim quote, names what
worked, and gives at most three fixes that quote what was said and what to say instead. The
learner's own reference answer is context, never evidence: it says what they meant to say.
A practice review never moves the roadmap and never claims to have changed anything.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
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

PRACTICE_REVIEW_SCHEMA_ID = "urn:tamforge:schema:practice-review-v1"
PRACTICE_REVIEW_JOB_TYPE = "claude.practice_review"
PRACTICE_REVIEW_MAX_TURNS = 4
PRACTICE_REVIEW_WALL_TIME_SECONDS = 180.0
PRACTICE_REVIEW_PROMPT_VERSION = "v1"
MINIMUM_ANSWER_WORDS = 8
MAX_ANSWER_CHARS = 40_000
# The interview tracker's dimensions a single uninterrupted answer can show. Follow-up
# handling is left out: a practice answer has no follow-up to handle.
PRACTICE_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("answer_clarity", "Answer clarity and structure"),
    ("technical_examples", "Technical examples and supporting evidence"),
    ("english_accuracy", "English accuracy visible in the transcript"),
)
COMPLETION_MARKERS = (
    "i marked",
    "i recorded",
    "i scheduled",
    "i completed",
    "i updated",
    "i saved",
    "i changed",
)


class PracticeReviewUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the answer stays unreviewed for now."""


@dataclass(frozen=True, slots=True)
class PracticeReviewRequest:
    question: str
    answer_transcript: str
    reference_answer: str = ""
    speech_metrics: Mapping[str, object] = field(default_factory=dict)
    repair_errors: tuple[str, ...] = ()


class PracticeDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(min_length=1, max_length=64)
    score: Decimal = Field(ge=0, le=4)
    evidence: str = Field(min_length=1, max_length=300)
    note: str = Field(min_length=1, max_length=400)


class PracticeFix(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heard: str = Field(min_length=1, max_length=300)
    say_instead: str = Field(min_length=1, max_length=400)
    why: str = Field(min_length=1, max_length=300)


class PracticeReviewOutcome(BaseModel):
    """The only shape a practice review may take."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: tuple[PracticeDimension, ...] = Field(min_length=1, max_length=3)
    strengths: tuple[str, ...] = Field(min_length=1, max_length=3)
    fixes: tuple[PracticeFix, ...] = Field(min_length=1, max_length=3)
    reference_coverage: str = Field(max_length=600)
    readiness: Literal["draft", "drilling", "ready"]


class PracticeReviewTransport(Protocol):
    async def review_practice(self, request: PracticeReviewRequest) -> Mapping[str, object]: ...


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def validate_practice_review(
    payload: Mapping[str, object], *, answer_transcript: str
) -> tuple[str, ...]:
    """Issues by name; empty means the review may be stored."""
    try:
        outcome = PracticeReviewOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "review"
        return (f"review {location}: {first['msg']}",)
    expected = [slug for slug, _ in PRACTICE_DIMENSIONS]
    if sorted(d.slug for d in outcome.dimensions) != sorted(expected):
        return ("the review must score exactly these dimensions once: " + ", ".join(expected),)
    haystack = _normalize(answer_transcript)
    for dimension in outcome.dimensions:
        if dimension.score != dimension.score.quantize(Decimal("0.5")):
            return (f"dimension {dimension.slug} must be scored in half points",)
        if _normalize(dimension.evidence) not in haystack:
            return (f"dimension {dimension.slug} evidence must be a verbatim quote of the answer",)
    for fix in outcome.fixes:
        if _normalize(fix.heard) not in haystack:
            return ("every fix must quote what was heard, verbatim, from the answer",)
    lowered = " ".join(
        [
            *(d.note for d in outcome.dimensions),
            *outcome.strengths,
            *(f"{f.say_instead} {f.why}" for f in outcome.fixes),
            outcome.reference_coverage,
        ]
    ).lower()
    for marker in COMPLETION_MARKERS:
        if marker in lowered:
            return ("the review cannot claim to have recorded, saved or changed anything",)
    return ()


@dataclass
class _PracticeReviewRuntimeAdapter:
    transport: PracticeReviewTransport
    request: PracticeReviewRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = PracticeReviewRequest(
            question=self.request.question,
            answer_transcript=self.request.answer_transcript,
            reference_answer=self.request.reference_answer,
            speech_metrics=self.request.speech_metrics,
            repair_errors=repair_errors,
        )
        payload = await self.transport.review_practice(request)
        return TransportResult(payload=payload, turns=1)


class PracticeReviewService:
    def __init__(self, transport: PracticeReviewTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def review(self, request: PracticeReviewRequest) -> PracticeReviewOutcome:
        """One bounded review, or a contract error the caller renders as such."""
        if not request.question.strip():
            raise RoleContractError("the practice review needs the question that was asked")
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", request.answer_transcript)
        if len(words) < MINIMUM_ANSWER_WORDS:
            raise RoleContractError("the answer is too short to review")
        if len(request.answer_transcript) > MAX_ANSWER_CHARS:
            raise RoleContractError("the answer is longer than the review may read")
        prepare_role_prompt(
            AgentRole.REVIEWER,
            committed=True,
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SPEECH_METRICS),
        )
        if self._transport is None:
            raise PracticeReviewUnavailable(
                "the practice review needs Claude enabled on the server"
            )
        runtime = BoundedClaudeRuntime(
            _PracticeReviewRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_practice_review(
                payload, answer_transcript=request.answer_transcript
            ),
        )
        digest = hashlib.sha256(
            f"{request.question}:{request.answer_transcript}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"practice-review:{digest}",
            job_type=PRACTICE_REVIEW_JOB_TYPE,
            model=self._model,
            schema_id=PRACTICE_REVIEW_SCHEMA_ID,
            prompt_version=PRACTICE_REVIEW_PROMPT_VERSION,
            max_turns=PRACTICE_REVIEW_MAX_TURNS,
            wall_time_seconds=PRACTICE_REVIEW_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise PracticeReviewUnavailable("the review did not return a valid outcome") from None
        except AgentRuntimeError as exc:
            raise PracticeReviewUnavailable(str(exc)) from None
        return PracticeReviewOutcome.model_validate(result.payload)


def practice_review_schema() -> dict[str, object]:
    return PracticeReviewOutcome.model_json_schema()


def render_practice_review_prompt(request: PracticeReviewRequest) -> str:
    """The prompt the SDK transport sends: the question, the answer, the context."""
    lines: list[str] = [
        "A learner preparing for Technical Account Manager interviews practised one answer "
        "aloud, uninterrupted. This is practice, not a real interview.",
        f"Question asked: {request.question.strip()}",
        "The learner's answer, transcribed from the recording:\n"
        + request.answer_transcript.strip(),
    ]
    if request.reference_answer.strip():
        lines.append(
            "The learner's own reference answer (what they intended to say, not evidence of "
            "what they can do):\n" + request.reference_answer.strip()
        )
    if request.speech_metrics:
        lines.append(
            "Speech metrics measured on the recording:\n"
            + "\n".join(f"- {key}: {value}" for key, value in request.speech_metrics.items())
        )
    lines.append(
        "Score exactly these dimensions, each once, in half points from 0 to 4, each with a "
        "verbatim quote of the answer as evidence and a one-line note:\n"
        + "\n".join(f"- {slug}: {name}" for slug, name in PRACTICE_DIMENSIONS)
    )
    lines.append(
        "Then name one to three strengths; give one to three fixes, each quoting what was "
        "heard verbatim, what to say instead, and why; say in reference_coverage what the "
        "answer left out of the learner's own reference answer (empty when there is none); "
        "and set readiness to draft, drilling or ready. Judge only the transcribed answer. "
        "Never claim to have recorded, saved or changed anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous answer was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)


__all__ = [
    "PRACTICE_DIMENSIONS",
    "PRACTICE_REVIEW_JOB_TYPE",
    "PRACTICE_REVIEW_PROMPT_VERSION",
    "PRACTICE_REVIEW_SCHEMA_ID",
    "PracticeDimension",
    "PracticeFix",
    "PracticeReviewOutcome",
    "PracticeReviewRequest",
    "PracticeReviewService",
    "PracticeReviewTransport",
    "PracticeReviewUnavailable",
    "practice_review_schema",
    "render_practice_review_prompt",
    "validate_practice_review",
]
