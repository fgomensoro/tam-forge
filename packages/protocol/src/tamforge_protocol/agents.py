"""Versioned prepared-text analysis contracts, not evidence publication authority.

References locate immutable evidence but do not prove ownership, consent, source
existence, or publication eligibility. Those checks belong to the later resolver.
Text offsets are exclusive-end Unicode code points, without normalization.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PositiveId = Annotated[int, Field(strict=True, gt=0)]
Codepoint = Annotated[int, Field(strict=True, ge=0, le=16 * 1024 * 1024)]
Milliseconds = Annotated[int, Field(strict=True, ge=0, le=86_400_000)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
VersionKey = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
Slug = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048, pattern=r"\S")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttemptTextReference(_StrictModel):
    """Offsets within the decoded string selected from the committed JSON envelope."""

    kind: Literal["attempt_text"]
    attempt_id: PositiveId
    commitment_sha256: Hash
    json_pointer: Annotated[
        str, StringConstraints(strict=True, max_length=512, pattern=r"^/output/(?:[^~]|~[01])*$")
    ]
    start_codepoint: Codepoint
    end_codepoint: Codepoint

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("text range must be nonempty and ordered")
        return self


class ArtifactTextReference(_StrictModel):
    """Offsets within exact UTF-8-decoded plain text, not a structured transcript."""

    kind: Literal["artifact_text"]
    artifact_id: PositiveId
    immutable_version: PositiveId
    sha256: Hash
    text_kind: Literal["written", "raw_transcript", "corrected_transcript"]
    start_codepoint: Codepoint
    end_codepoint: Codepoint

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.start_codepoint >= self.end_codepoint:
            raise ValueError("text range must be nonempty and ordered")
        return self


class ArtifactTimeReference(_StrictModel):
    kind: Literal["artifact_time"]
    artifact_id: PositiveId
    immutable_version: PositiveId
    sha256: Hash
    start_ms: Milliseconds
    end_ms: Milliseconds

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.start_ms >= self.end_ms:
            raise ValueError("time range must be nonempty and ordered")
        return self


EvidenceReference = Annotated[
    AttemptTextReference | ArtifactTextReference | ArtifactTimeReference,
    Field(discriminator="kind"),
]


class AnalysisObservation(_StrictModel):
    statement: Text
    attribution: Literal["observed_content", "user_stated", "inferred", "unknown"]
    availability: Literal["available", "unavailable"]
    confidence: Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
    references: Annotated[tuple[EvidenceReference, ...], Field(max_length=16)] = ()

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        if len(set(self.references)) != len(self.references):
            raise ValueError("evidence references must be unique")
        return self


def require_attributed_evidence(
    observations: Iterable[AnalysisObservation], *, what: str
) -> None:
    """A claim the learner is scored or corrected on has to cite something real.

    Available, referenced, and attributed to one of the three known kinds of claim. An
    unknown attribution is the reviewer saying it does not know where this came from,
    which is not a basis for a score or for asking someone to redo work.
    """
    for observation in observations:
        if (
            observation.availability != "available"
            or not observation.references
            or observation.attribution == "unknown"
        ):
            raise ValueError(f"{what} require available attributed evidence")


class ScoredDimension(_StrictModel):
    availability: Literal["scored"]
    score: Annotated[Decimal, Field(ge=0, le=4, allow_inf_nan=False)]
    rationale: Text
    observations: Annotated[tuple[AnalysisObservation, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def supported_score(self) -> Self:
        require_attributed_evidence(self.observations, what="scored dimensions")
        return self


class UnassessedDimension(_StrictModel):
    availability: Literal["unavailable", "not_applicable"]
    score: None = None
    reason_code: Slug
    explanation: Text


Dimension = Annotated[ScoredDimension | UnassessedDimension, Field(discriminator="availability")]


class _Dimensions(_StrictModel):
    def values(self) -> tuple[Dimension, ...]:
        return tuple(getattr(self, key) for key in type(self).model_fields)


class EnglishDimensions(_Dimensions):
    communication_effectiveness: Dimension
    fluency: Dimension
    accuracy: Dimension
    vocabulary: Dimension
    pronunciation_intelligibility: Dimension
    listening: Dimension


class TAMDimensions(_Dimensions):
    correctness: Dimension
    structure: Dimension
    relevance: Dimension
    customer_judgment: Dimension
    technical_reasoning: Dimension
    business_framing: Dimension
    trade_offs: Dimension
    audience_adaptation: Dimension
    decision_quality: Dimension


class _Analysis(_StrictModel):
    activity_id: PositiveId
    attempt_id: PositiveId
    config_version_key: VersionKey
    rubric_slug: Slug
    rubric_version: VersionKey

    @model_validator(mode="after")
    def bounded_payload(self) -> Self:
        encoded = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            raise ValueError("analysis payload exceeds 1 MiB")
        return self

    def validate_text_support(self, dimensions: _Dimensions, *, english: bool) -> None:
        for dimension in dimensions.values():
            if not isinstance(dimension, ScoredDimension):
                continue
            for observation in dimension.observations:
                prepared_text = False
                for ref in observation.references:
                    if isinstance(ref, AttemptTextReference):
                        if ref.attempt_id != self.attempt_id:
                            raise ValueError("text reference must identify the analysis attempt")
                        prepared_text = True
                    elif (
                        isinstance(ref, ArtifactTextReference) and ref.text_kind != "raw_transcript"
                    ):
                        prepared_text = True
                    elif english:
                        raise ValueError(
                            "English v1 scores require prepared text, not raw ASR or timing"
                        )
                if not prepared_text:
                    raise ValueError("v1 scored observations require prepared text evidence")


class EnglishAnalysisV1(_Analysis):
    """Text judgments only; speech measurements require a future contract version."""

    model_config = ConfigDict(json_schema_extra={"$id": "urn:tamforge:schema:english-analysis-v1"})
    analysis_kind: Literal["english_analysis"]
    schema_version: Literal["english-analysis-v1"]
    source_mode: Literal["written", "monologue_transcript", "interactive_transcript"]
    dimensions: EnglishDimensions

    @model_validator(mode="after")
    def supported_capabilities(self) -> Self:
        for dimension, reason in (
            (self.dimensions.fluency, "speech_pipeline_unavailable"),
            (self.dimensions.pronunciation_intelligibility, "pronunciation_not_measured"),
        ):
            if (
                not isinstance(dimension, UnassessedDimension)
                or dimension.availability != "unavailable"
                or dimension.reason_code != reason
            ):
                raise ValueError("v1 speech dimensions must remain explicitly unavailable")
        listening = self.dimensions.listening
        expected = (
            "unavailable" if self.source_mode == "interactive_transcript" else "not_applicable"
        )
        if not isinstance(listening, UnassessedDimension) or listening.availability != expected:
            raise ValueError("listening availability must match the unvalidated source modality")
        self.validate_text_support(self.dimensions, english=True)
        return self


class TAMAnalysisV1(_Analysis):
    model_config = ConfigDict(json_schema_extra={"$id": "urn:tamforge:schema:tam-analysis-v1"})
    analysis_kind: Literal["tam_analysis"]
    schema_version: Literal["tam-analysis-v1"]
    dimensions: TAMDimensions

    @model_validator(mode="after")
    def prepared_text_judgments(self) -> Self:
        self.validate_text_support(self.dimensions, english=False)
        return self


WithheldReason = Literal[
    "self_review_pending",
    "evidence_unavailable",
    "evidence_out_of_manifest",
    "version_mismatch",
    "forbidden_source",
]


# One report says two things went well and two things to fix next, and nothing more.
# The number is the point: a list of nine corrections is a list nobody acts on.
REQUIRED_STRENGTHS = 2
REQUIRED_CORRECTIONS = 2
# Attempt B is a bounded redo inside the next lesson, not a second full attempt.
ATTEMPT_B_MAX_MINUTES = 10
# At most two corrections enter the next lesson, which is the same two the report named.
MAX_NEXT_LESSON_CORRECTIONS = REQUIRED_CORRECTIONS
# There is no Attempt C. A second redo of the same work stops being practice and starts
# being memorization of one answer, and later transfer needs a new independent
# Attempt A instead.
ATTEMPT_LABELS: tuple[str, ...] = ("attempt_a", "attempt_b")


def next_attempt_label(existing: Iterable[str]) -> str:
    """Return the label of the attempt that may be scheduled next, or refuse."""
    taken = tuple(existing)
    for label in ATTEMPT_LABELS:
        if label not in taken:
            return label
    raise ValueError("no attempt after Attempt B may be scheduled")


class FeedbackStrength(_StrictModel):
    """Something the learner demonstrated, with the evidence that shows it."""

    statement: Text
    evidence: AnalysisObservation

    @model_validator(mode="after")
    def supported(self) -> Self:
        require_attributed_evidence((self.evidence,), what="strengths")
        return self


class FeedbackCorrection(_StrictModel):
    """One of the two highest-impact fixes, with what to actually do about it."""

    statement: Text
    instruction: Text
    target_skill: Slug
    evidence: AnalysisObservation

    @model_validator(mode="after")
    def supported(self) -> Self:
        require_attributed_evidence((self.evidence,), what="corrections")
        return self


class AttemptBInstruction(_StrictModel):
    """The bounded redo the learner is asked for, in minutes they actually have."""

    instruction: Text
    minutes: Annotated[int, Field(strict=True, ge=1, le=ATTEMPT_B_MAX_MINUTES)]
    # The prompt Attempt B runs against. It has to be the one the analysis was produced
    # from, or the comparison between the two attempts compares two different tasks.
    core_prompt_sha256: Hash


ComparisonOutcome = Literal["improved", "partially_improved", "not_improved"]

# What happens to the correction once the two attempts have been compared. Neither
# outcome schedules another attempt: an unresolved correction comes back later in a
# different scenario, which is the only thing that distinguishes learning from
# rehearsing one prompt.
CorrectionDisposition = Literal["resolved", "retrieval_queued"]


class AttemptComparison(_StrictModel):
    """The judgment on one correction, from Attempt A and Attempt B and nothing else."""

    attempt_a_id: PositiveId
    attempt_b_id: PositiveId
    comparator_version: VersionKey
    core_prompt_sha256: Hash
    outcome: ComparisonOutcome
    observations: Annotated[
        tuple[AnalysisObservation, ...], Field(min_length=1, max_length=8)
    ]

    @model_validator(mode="after")
    def two_distinct_attempts(self) -> Self:
        if self.attempt_a_id == self.attempt_b_id:
            raise ValueError("a comparison needs two distinct attempts")
        return self

    @model_validator(mode="after")
    def supported_outcome(self) -> Self:
        require_attributed_evidence(self.observations, what="comparisons")
        return self


class TransferError(ValueError):
    """This attempt cannot retire the queued correction."""


class QueuedRetrieval(_StrictModel):
    """A correction Attempt B did not resolve, waiting for a different scenario."""

    target_skill: Slug
    source_scenario_key: Slug
    source_core_prompt_sha256: Hash
    queued_from_attempt_b_id: PositiveId


class TransferAttempt(_StrictModel):
    """The later, independent attempt that may retire a queued correction.

    The label is fixed. Transfer is demonstrated by doing the thing again somewhere new
    and unaided, so it needs a fresh Attempt A rather than another pass at the redo,
    and Attempt B never creates qualifying evidence of its own.
    """

    attempt_id: PositiveId
    attempt_label: Literal["attempt_a"]
    scenario_key: Slug
    core_prompt_sha256: Hash


def require_material_difference(queued: QueuedRetrieval, attempt: TransferAttempt) -> None:
    """Raise unless the later attempt is materially different from the one queued it.

    Repeating the original prompt measures recall of one answer, and marking a
    correction demonstrated on that basis is how a weakness disappears from the record
    without ever being fixed.
    """
    if attempt.core_prompt_sha256 == queued.source_core_prompt_sha256:
        raise TransferError("a repeat of the original prompt cannot demonstrate transfer")
    if attempt.scenario_key == queued.source_scenario_key:
        raise TransferError("a repeat of the original scenario cannot demonstrate transfer")
    if attempt.attempt_id == queued.queued_from_attempt_b_id:
        raise TransferError("transfer needs a new attempt, not the one that queued it")


def close_correction(comparison: AttemptComparison) -> CorrectionDisposition:
    """Return what happens to the correction. Never a third attempt at the same prompt."""
    if comparison.outcome == "improved":
        return "resolved"
    return "retrieval_queued"


class PinnedRecord(_StrictModel):
    """One immutable provenance row identified by id and content hash."""

    id: PositiveId
    content_hash: Hash


class AnalysisVersions(_StrictModel):
    model_run: PinnedRecord
    prompt: PinnedRecord
    output_schema: PinnedRecord
    rubric_binding: PinnedRecord


class FeedbackRead(_StrictModel):
    """Validated construction cannot produce analysis outside `ready`; frozen fields keep it so.

    Like every model here, `model_construct` and `model_copy` skip validators. Assemble a
    response through `__init__` or `model_validate`, and revalidate at any boundary that
    accepts one from elsewhere, the way `agents/model_runs.py` revalidates its run requests.
    """

    status: Literal["processing", "needs_attention", "ready"]
    activity_id: PositiveId
    attempt_id: PositiveId
    versions: AnalysisVersions | None = None
    english: EnglishAnalysisV1 | None = None
    tam: TAMAnalysisV1 | None = None
    withheld_reason: WithheldReason | None = None
    verdict: Text | None = None
    strengths: Annotated[
        tuple[FeedbackStrength, ...], Field(max_length=REQUIRED_STRENGTHS)
    ] = ()
    corrections: Annotated[
        tuple[FeedbackCorrection, ...], Field(max_length=REQUIRED_CORRECTIONS)
    ] = ()
    attempt_b: AttemptBInstruction | None = None

    @model_validator(mode="after")
    def release_gate(self) -> Self:
        if self.status != "ready":
            if self.english is not None or self.tam is not None or self.versions is not None:
                raise ValueError("withheld feedback must not carry analysis or versions")
            if (self.status == "needs_attention") != (self.withheld_reason is not None):
                raise ValueError("only needs_attention carries a withholding reason")
            if self.verdict is not None or self.strengths or self.corrections:
                raise ValueError("withheld feedback must not carry a verdict or its findings")
            if self.attempt_b is not None:
                raise ValueError("withheld feedback must not ask for an Attempt B")
            return self
        if self.english is None or self.tam is None or self.versions is None:
            raise ValueError("ready feedback requires both analyses and their versions")
        if self.withheld_reason is not None:
            raise ValueError("ready feedback cannot carry a withholding reason")
        if self.verdict is None or self.attempt_b is None:
            raise ValueError("ready feedback requires a verdict and an Attempt B instruction")
        if len(self.strengths) != REQUIRED_STRENGTHS:
            raise ValueError("ready feedback names exactly two demonstrated strengths")
        if len(self.corrections) != REQUIRED_CORRECTIONS:
            raise ValueError("ready feedback names exactly two highest-impact corrections")
        if self.attempt_b.core_prompt_sha256 != self.versions.prompt.content_hash:
            raise ValueError("Attempt B must run against the same core prompt as the analysis")
        for label, statements in (
            ("strengths", [item.statement for item in self.strengths]),
            ("corrections", [item.statement for item in self.corrections]),
        ):
            # The same point twice fills a slot without adding a finding, which is the
            # cheapest way to satisfy a count and the least useful.
            if len({statement.strip().casefold() for statement in statements}) != len(statements):
                raise ValueError(f"the two {label} must be distinct")
        for analysis in (self.english, self.tam):
            if (analysis.activity_id, analysis.attempt_id) != (self.activity_id, self.attempt_id):
                raise ValueError("released analysis must identify the read attempt")
        return self
