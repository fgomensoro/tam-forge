"""Pure publication decisions. Loading state is the caller's job, deciding is ours."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tamforge_protocol.agents import (
    AttemptTextReference,
    EnglishAnalysisV1,
    EvidenceReference,
    ScoredDimension,
    TAMAnalysisV1,
    WithheldReason,
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
