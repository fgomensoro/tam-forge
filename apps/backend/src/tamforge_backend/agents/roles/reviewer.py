"""Pure publication decisions. Loading state is the caller's job, deciding is ours."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tamforge_protocol.agents import (
    AttemptTextReference,
    EnglishAnalysisV1,
    EvidenceReference,
    ScoredDimension,
    TAMAnalysisV1,
    WithheldReason,
)

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
    RUBRIC,
    SELF_REVIEW,
    SPEECH_METRICS,
    TASK_BRIEF,
    RoleContractError,
    prepare_role_prompt,
)

# Publication is possible only once the learner's own reflection is on record. These are every
# state at or past self_review_complete, matching what evidence/repository.py already accepts for
# external evaluation, so a closed activity is not mistaken for a pending self-review.
RELEASABLE_ACTIVITY_STATES = frozenset(
    {
        "self_review_complete",
        "ai_processing",
        "feedback_ready",
        "correction_due",
        "demonstrated",
        "needs_work",
    }
)
FORBIDDEN_ARTIFACT_CLASSES = frozenset({"original_audio"})


@dataclass(frozen=True, slots=True)
class ArtifactFact:
    """The stored identity of one artifact already linked to the analysed attempt."""

    immutable_version: int
    sha256: str
    artifact_class: str


@dataclass(frozen=True, slots=True)
class ReleaseInput:
    activity_state: str
    self_review_committed: bool
    attempt_commitment_sha256: str
    manifest: tuple[EvidenceReference, ...]
    rubric_slug: str
    rubric_version: str
    linked_artifacts: Mapping[int, ArtifactFact]


def _cited_references(
    analysis: EnglishAnalysisV1 | TAMAnalysisV1,
) -> tuple[EvidenceReference, ...]:
    references: list[EvidenceReference] = []
    for dimension in analysis.dimensions.values():
        if isinstance(dimension, ScoredDimension):
            for observation in dimension.observations:
                references.extend(observation.references)
    return tuple(references)


def _reference_withholding(
    reference: EvidenceReference, analysis: EnglishAnalysisV1 | TAMAnalysisV1, state: ReleaseInput
) -> WithheldReason | None:
    if isinstance(reference, AttemptTextReference):
        if (
            reference.attempt_id != analysis.attempt_id
            or reference.commitment_sha256 != state.attempt_commitment_sha256
        ):
            return "evidence_unavailable"
        return None
    fact = state.linked_artifacts.get(reference.artifact_id)
    if (
        fact is None
        or fact.immutable_version != reference.immutable_version
        or fact.sha256 != reference.sha256
    ):
        return "evidence_unavailable"
    if fact.artifact_class in FORBIDDEN_ARTIFACT_CLASSES:
        return "forbidden_source"
    return None


def evaluate_release(
    *, english: EnglishAnalysisV1, tam: TAMAnalysisV1, state: ReleaseInput
) -> WithheldReason | None:
    """Return None to release, or the closed reason the output stays withheld."""
    if not state.self_review_committed or state.activity_state not in RELEASABLE_ACTIVITY_STATES:
        return "self_review_pending"
    manifest = frozenset(state.manifest)
    for analysis in (english, tam):
        if (analysis.rubric_slug, analysis.rubric_version) != (
            state.rubric_slug,
            state.rubric_version,
        ):
            return "version_mismatch"
        for reference in _cited_references(analysis):
            if reference not in manifest:
                return "evidence_out_of_manifest"
            withheld = _reference_withholding(reference, analysis, state)
            if withheld is not None:
                return withheld
    return None


# ---------------------------------------------------------------------------------------
# The reviewer's scoring contract: one bounded turn that scores a committed attempt
# against the block's rubric. It judges; it never completes, schedules or records.
# ---------------------------------------------------------------------------------------

REVIEW_SCHEMA_ID = "urn:tamforge:schema:reviewer-v1"
REVIEW_JOB_TYPE = "claude.review"
REVIEW_MAX_TURNS = 4
REVIEW_WALL_TIME_SECONDS = 240.0
REVIEW_PROMPT_VERSION = "v1"


class ReviewerUnavailable(RoleContractError):
    """Claude is disabled or the runtime failed; the attempt stays unscored for now."""


@dataclass(frozen=True, slots=True)
class ReviewDimension:
    slug: str
    name: str
    maximum: Decimal


@dataclass(frozen=True, slots=True)
class ReviewBlock:
    stable_id: str
    objective: str
    required_output: tuple[str, ...]
    pass_criteria: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    block: ReviewBlock
    rubric_slug: str
    rubric_version: str
    dimensions: tuple[ReviewDimension, ...]
    committed_attempt: str
    self_review: str | None = None
    transcript: str | None = None
    speech_metrics: Mapping[str, object] | None = None
    repair_errors: tuple[str, ...] = ()


class ScoredReviewDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(min_length=1, max_length=64)
    score: Decimal = Field(ge=0, le=20)
    rationale: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=500)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=1, max_length=500)
    instruction: str = Field(default="", max_length=500)


class ReviewOutcome(BaseModel):
    """The only shape a review may take: scores with reasons, two strengths, two corrections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: str = Field(min_length=1, max_length=1000)
    dimensions: tuple[ScoredReviewDimension, ...] = Field(min_length=1, max_length=16)
    strengths: tuple[ReviewFinding, ...] = Field(min_length=2, max_length=2)
    corrections: tuple[ReviewFinding, ...] = Field(min_length=2, max_length=2)
    next_practice: str = Field(min_length=1, max_length=500)


class ReviewTransport(Protocol):
    async def review(self, request: ReviewRequest) -> Mapping[str, object]: ...


def validate_review(
    payload: Mapping[str, object], *, dimensions: Sequence[ReviewDimension]
) -> tuple[str, ...]:
    """Issues by name; empty means the review may be stored and scored."""
    try:
        outcome = ReviewOutcome.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "review"
        return (f"review {location}: {first['msg']}",)
    expected = {item.slug: item for item in dimensions}
    given = [item.slug for item in outcome.dimensions]
    if sorted(given) != sorted(expected):
        return ("the review must score exactly the rubric's dimensions: " + ", ".join(expected),)
    for item in outcome.dimensions:
        if item.score > expected[item.slug].maximum:
            return (f"dimension {item.slug} exceeds its maximum {expected[item.slug].maximum}",)
        if item.score != item.score.quantize(Decimal("0.5")):
            return (f"dimension {item.slug} must be scored in half points",)
    lowered = " ".join(
        [outcome.verdict, outcome.next_practice]
        + [f.statement for f in outcome.strengths + outcome.corrections]
    ).lower()
    for marker in ("marked as done", "i marked", "i recorded", "i scheduled", "i completed"):
        if marker in lowered:
            return ("the reviewer cannot claim to have recorded, scheduled or completed anything",)
    if len({f.statement.casefold() for f in outcome.corrections}) < 2:
        return ("the two corrections must be distinct",)
    if len({f.statement.casefold() for f in outcome.strengths}) < 2:
        return ("the two strengths must be distinct",)
    return ()


@dataclass
class _ReviewRuntimeAdapter:
    transport: ReviewTransport
    request: ReviewRequest

    async def invoke(
        self, run: PreparedAgentRun, *, repair_errors: tuple[str, ...] = ()
    ) -> TransportResult:
        del run
        request = ReviewRequest(
            block=self.request.block,
            rubric_slug=self.request.rubric_slug,
            rubric_version=self.request.rubric_version,
            dimensions=self.request.dimensions,
            committed_attempt=self.request.committed_attempt,
            self_review=self.request.self_review,
            transcript=self.request.transcript,
            speech_metrics=self.request.speech_metrics,
            repair_errors=repair_errors,
        )
        payload = await self.transport.review(request)
        return TransportResult(payload=payload, turns=1)


class ReviewerService:
    def __init__(self, transport: ReviewTransport | None, *, model: str) -> None:
        self._transport = transport
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def review(self, request: ReviewRequest) -> ReviewOutcome:
        """One bounded review, or a contract error the caller renders as such."""
        if not request.committed_attempt.strip():
            raise RoleContractError("the reviewer scores only a committed attempt")
        if not request.dimensions:
            raise RoleContractError("the reviewer needs the block's rubric")
        prepare_role_prompt(
            AgentRole.REVIEWER,
            committed=True,
            requested_context=(TASK_BRIEF, COMMITTED_ATTEMPT, SELF_REVIEW, RUBRIC, SPEECH_METRICS),
        )
        if self._transport is None:
            raise ReviewerUnavailable("the reviewer needs Claude enabled on the server")
        runtime = BoundedClaudeRuntime(
            _ReviewRuntimeAdapter(self._transport, request),
            validate=lambda payload: validate_review(payload, dimensions=request.dimensions),
        )
        digest = hashlib.sha256(
            f"{request.block.stable_id}:{request.rubric_slug}:{request.committed_attempt}".encode()
        ).hexdigest()[:24]
        prepared = PreparedAgentRun(
            run_key=f"review:{request.block.stable_id}:{digest}",
            job_type=REVIEW_JOB_TYPE,
            model=self._model,
            schema_id=REVIEW_SCHEMA_ID,
            prompt_version=REVIEW_PROMPT_VERSION,
            max_turns=REVIEW_MAX_TURNS,
            wall_time_seconds=REVIEW_WALL_TIME_SECONDS,
        )
        try:
            result = await runtime.run(prepared)
        except AgentOutputInvalid:
            raise ReviewerUnavailable("the reviewer did not return a valid review") from None
        except AgentRuntimeError as exc:
            raise ReviewerUnavailable(str(exc)) from None
        return ReviewOutcome.model_validate(result.payload)


def review_schema() -> dict[str, object]:
    return ReviewOutcome.model_json_schema()


def render_review_prompt(request: ReviewRequest) -> str:
    """The prompt the SDK transport sends: the brief, the rubric, the attempt, the evidence."""
    lines: list[str] = [
        f"Block: {request.block.stable_id}. Objective: {request.block.objective}",
        "Required output: " + "; ".join(request.block.required_output),
        "Pass criteria: " + "; ".join(request.block.pass_criteria),
        f"Rubric {request.rubric_slug} {request.rubric_version}. Score every dimension "
        "below in half points from 0 to its maximum, with a one-sentence rationale and a "
        "short verbatim quote from the attempt or transcript as evidence:",
        "\n".join(
            f"- {item.slug}: {item.name} (maximum {item.maximum})" for item in request.dimensions
        ),
        "Committed attempt:\n" + request.committed_attempt,
    ]
    if request.self_review:
        lines.append("Learner's self-review:\n" + request.self_review)
    if request.transcript:
        lines.append(
            "Spoken transcript (learner and other party, with timestamps):\n" + request.transcript
        )
    if request.speech_metrics:
        lines.append(
            "Speech metrics:\n"
            + "\n".join(f"- {key}: {value}" for key, value in request.speech_metrics.items())
        )
    lines.append(
        "Return a verdict, exactly two strengths and two corrections (each correction with an "
        "instruction), and one next practice. Judge only what is on the page; never claim to "
        "have recorded, scheduled or completed anything."
    )
    if request.repair_errors:
        lines.append(
            "Your previous review was refused; fix these:\n"
            + "\n".join(f"- {error}" for error in request.repair_errors)
        )
    return "\n\n".join(lines)
