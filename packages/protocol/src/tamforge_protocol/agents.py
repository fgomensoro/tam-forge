"""Versioned prepared-text analysis contracts, not evidence publication authority.

References locate immutable evidence but do not prove ownership, consent, source
existence, or publication eligibility. Those checks belong to the later resolver.
Text offsets are exclusive-end Unicode code points, without normalization.
"""

from __future__ import annotations

import json
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


class ScoredDimension(_StrictModel):
    availability: Literal["scored"]
    score: Annotated[Decimal, Field(ge=0, le=4, allow_inf_nan=False)]
    rationale: Text
    observations: Annotated[tuple[AnalysisObservation, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def supported_score(self) -> Self:
        for observation in self.observations:
            if (
                observation.availability != "available"
                or not observation.references
                or observation.attribution == "unknown"
            ):
                raise ValueError("scored dimensions require available attributed evidence")
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
