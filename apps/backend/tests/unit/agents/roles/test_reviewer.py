"""Pure release decisions for prepared Reviewer output."""

from __future__ import annotations

import pytest
from tamforge_protocol.agents import (
    ArtifactTextReference,
    AttemptTextReference,
    EnglishAnalysisV1,
    TAMAnalysisV1,
)

ATTEMPT_HASH = "a" * 64
ARTIFACT_HASH = "b" * 64
ENGLISH_UNAVAILABLE = {
    "fluency": {
        "availability": "unavailable",
        "score": None,
        "reason_code": "speech_pipeline_unavailable",
        "explanation": "Speech pipeline is not installed.",
    },
    "pronunciation_intelligibility": {
        "availability": "unavailable",
        "score": None,
        "reason_code": "pronunciation_not_measured",
        "explanation": "Calibrated diagnostic did not run.",
    },
    "listening": {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "written_source",
        "explanation": "Written submission has no listening evidence.",
    },
}


def attempt_reference(attempt_id=9, commitment=ATTEMPT_HASH):
    return AttemptTextReference(
        kind="attempt_text",
        attempt_id=attempt_id,
        commitment_sha256=commitment,
        json_pointer="/output/draft_markdown",
        start_codepoint=0,
        end_codepoint=4,
    )


def artifact_reference(artifact_id=3, immutable_version=1, sha256=ARTIFACT_HASH):
    return ArtifactTextReference(
        kind="artifact_text",
        artifact_id=artifact_id,
        immutable_version=immutable_version,
        sha256=sha256,
        text_kind="written",
        start_codepoint=0,
        end_codepoint=4,
    )


def scored(reference):
    return {
        "availability": "scored",
        "score": 3,
        "rationale": "Supported by prepared text.",
        "observations": [
            {
                "statement": "The answer named the customer impact.",
                "attribution": "observed_content",
                "availability": "available",
                "confidence": "0.8",
                "references": [reference.model_dump(mode="json")],
            }
        ],
    }


def unscored():
    return {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "not_exercised",
        "explanation": "This dimension was not exercised.",
    }


def english(reference=None):
    reference = attempt_reference() if reference is None else reference
    dimensions = {
        "communication_effectiveness": scored(reference),
        "accuracy": unscored(),
        "vocabulary": unscored(),
        **ENGLISH_UNAVAILABLE,
    }
    return EnglishAnalysisV1.model_validate(
        {
            "analysis_kind": "english_analysis",
            "schema_version": "english-analysis-v1",
            "source_mode": "written",
            "activity_id": 7,
            "attempt_id": 9,
            "config_version_key": "seed-v1",
            "rubric_slug": "tam_case",
            "rubric_version": "seed-v1",
            "dimensions": dimensions,
        }
    )


def tam(reference=None, rubric_version="seed-v1"):
    reference = attempt_reference() if reference is None else reference
    keys = (
        "correctness",
        "structure",
        "relevance",
        "customer_judgment",
        "technical_reasoning",
        "business_framing",
        "trade_offs",
        "audience_adaptation",
        "decision_quality",
    )
    dimensions = {key: unscored() for key in keys}
    dimensions["correctness"] = scored(reference)
    return TAMAnalysisV1.model_validate(
        {
            "analysis_kind": "tam_analysis",
            "schema_version": "tam-analysis-v1",
            "activity_id": 7,
            "attempt_id": 9,
            "config_version_key": "seed-v1",
            "rubric_slug": "tam_case",
            "rubric_version": rubric_version,
            "dimensions": dimensions,
        }
    )


def state(**overrides):
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, ReleaseInput

    defaults = {
        "activity_state": "ai_processing",
        "self_review_committed": True,
        "attempt_commitment_sha256": ATTEMPT_HASH,
        "manifest": (attempt_reference(),),
        "rubric_slug": "tam_case",
        "rubric_version": "seed-v1",
        "linked_artifacts": {
            3: ArtifactFact(
                immutable_version=1, sha256=ARTIFACT_HASH, artifact_class="written_output"
            )
        },
    }
    defaults.update(overrides)
    return ReleaseInput(**defaults)


def test_release_passes_when_self_review_and_evidence_hold():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert evaluate_release(english=english(), tam=tam(), state=state()) is None


def test_uncommitted_self_review_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(self_review_committed=False))
        == "self_review_pending"
    )


@pytest.mark.parametrize("activity_state", ["active", "output_committed", "paused", "incomplete"])
def test_activity_before_self_review_completion_withholds(activity_state):
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(activity_state=activity_state))
        == "self_review_pending"
    )


@pytest.mark.parametrize(
    "activity_state",
    [
        "self_review_complete",
        "ai_processing",
        "feedback_ready",
        "correction_due",
        "demonstrated",
        "needs_work",
    ],
)
def test_every_state_at_or_past_self_review_releases(activity_state):
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(activity_state=activity_state))
        is None
    )


def test_rubric_version_disagreement_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(rubric_version="seed-v2"), state=state())
        == "version_mismatch"
    )


def test_reference_outside_the_run_manifest_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    assert (
        evaluate_release(english=english(), tam=tam(), state=state(manifest=()))
        == "evidence_out_of_manifest"
    )


def test_attempt_reference_with_a_stale_commitment_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    stale = attempt_reference(commitment="c" * 64)
    assert (
        evaluate_release(
            english=english(stale), tam=tam(stale), state=state(manifest=(stale,))
        )
        == "evidence_unavailable"
    )


def test_artifact_reference_with_a_changed_hash_withholds():
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, evaluate_release

    reference = artifact_reference()
    withheld = evaluate_release(
        english=english(reference),
        tam=tam(reference),
        state=state(
            manifest=(reference,),
            linked_artifacts={
                3: ArtifactFact(
                    immutable_version=1, sha256="e" * 64, artifact_class="written_output"
                )
            },
        ),
    )
    assert withheld == "evidence_unavailable"


def test_unlinked_artifact_withholds():
    from tamforge_backend.agents.roles.reviewer import evaluate_release

    reference = artifact_reference()
    assert (
        evaluate_release(
            english=english(reference),
            tam=tam(reference),
            state=state(manifest=(reference,), linked_artifacts={}),
        )
        == "evidence_unavailable"
    )


def test_original_audio_evidence_withholds():
    from tamforge_backend.agents.roles.reviewer import ArtifactFact, evaluate_release

    reference = artifact_reference()
    withheld = evaluate_release(
        english=english(reference),
        tam=tam(reference),
        state=state(
            manifest=(reference,),
            linked_artifacts={
                3: ArtifactFact(
                    immutable_version=1, sha256=ARTIFACT_HASH, artifact_class="original_audio"
                )
            },
        ),
    )
    assert withheld == "forbidden_source"
