from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tamforge_backend.learning.artifacts import (
    ArtifactCommitment,
    ArtifactValidationError,
    build_commitment_digest,
    build_upload_intent,
    verify_confirm_request,
    verify_stored_object,
)
from tamforge_backend.learning.contracts import ContractContext, validate_output_contract
from tamforge_backend.learning.enums import ActivityState
from tamforge_backend.learning.models import Attempt
from tamforge_backend.learning.schemas import IncompleteCommand, SelfReviewCommand
from tamforge_backend.learning.service import ActivityConflict, ActivityService
from tamforge_backend.learning.state_machine import ActivityStateError, transition
from tamforge_backend.storage.models import StoredObject, integrity_metadata


def _validated_output() -> object:
    return validate_output_contract(
        {
            "contract_version": 1,
            "kind": "writing",
            "prompt": "Write a customer update.",
            "audience": "Customer engineering lead",
            "time_limit_minutes": 35,
            "requested_action": "Confirm the rollback window.",
            "facts": ["Error rate rose after release 42."],
            "unknowns": ["Whether all regions are affected."],
            "tone": "Direct and calm",
            "word_or_character_limit": "150 words",
            "draft_markdown": (
                "We recommend a controlled rollback while we isolate the affected regions."
            ),
            "self_edit_notes": "Removed an unsupported root-cause claim.",
        },
        context=ContractContext(
            block="communication_spoken",
            source_hidden=False,
            timebox_minutes=35,
            task_stable_id="m1-w1-d01-writing",
            exercise_type="customer_incident_update",
            mapping_version="seed-v1",
            roadmap_version_key="month-1-v2",
            task_definition_id=9,
        ),
    )


def test_commitment_hash_covers_output_and_ordered_artifact_manifest() -> None:
    output = _validated_output()
    artifacts = (
        ArtifactCommitment(artifact_id=8, sha256="b" * 64, link_role="supporting"),
        ArtifactCommitment(artifact_id=7, sha256="a" * 64, link_role="original_output"),
    )

    digest = build_commitment_digest(output, artifacts)  # type: ignore[arg-type]
    same = build_commitment_digest(output, tuple(reversed(artifacts)))  # type: ignore[arg-type]
    changed = build_commitment_digest(
        output,  # type: ignore[arg-type]
        (replace(artifacts[0], sha256="c" * 64), artifacts[1]),
    )

    assert len(digest) == 32
    assert digest == same
    assert digest != changed


def test_server_generated_upload_intent_binds_owner_activity_hash_and_metadata() -> None:
    intent = build_upload_intent(
        owner_id=3,
        activity_id=5,
        artifact_class="written_output",
        sha256="a" * 64,
        byte_length=4,
        content_type="text/markdown",
        original_filename="answer.md",
    )

    assert intent.object_key == f"written_output/3/activity-5/{'a' * 64}"
    assert intent.metadata == {"activity-id": "5", "owner-id": "3"}
    verify_confirm_request(intent, object_key=intent.object_key)
    with pytest.raises(ArtifactValidationError, match="server-generated"):
        verify_confirm_request(
            intent,
            object_key=f"written_output/3/activity-999/{'a' * 64}",
        )


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [
        ("Text/Markdown", "answer.md"),
        ("text/markdown; charset=utf-8", "answer.md"),
        ("text/markdown", "folder/answer.md"),
        ("text/markdown", "é" * 300),
    ],
)
def test_upload_intent_rejects_metadata_that_postgres_cannot_store(
    content_type: str,
    filename: str,
) -> None:
    with pytest.raises(ArtifactValidationError):
        build_upload_intent(
            owner_id=3,
            activity_id=5,
            artifact_class="written_output",
            sha256="a" * 64,
            byte_length=4,
            content_type=content_type,
            original_filename=filename,
        )


@pytest.mark.parametrize("changed", ["key", "hash", "length", "owner"])
def test_object_confirmation_rejects_any_integrity_or_ownership_mismatch(changed: str) -> None:
    intent = build_upload_intent(
        owner_id=3,
        activity_id=5,
        artifact_class="written_output",
        sha256="a" * 64,
        byte_length=4,
        content_type="text/markdown",
        original_filename="answer.md",
    )
    key = intent.object_key
    digest = intent.sha256
    length = intent.byte_length
    metadata = dict(intent.metadata)
    if changed == "key":
        key = f"written_output/3/activity-6/{'a' * 64}"
    elif changed == "hash":
        key = f"written_output/3/activity-5/{'b' * 64}"
        digest = "b" * 64
    elif changed == "length":
        length = 5
    else:
        metadata["owner-id"] = "4"
    stored = StoredObject(
        key=key,
        sha256=digest,
        byte_length=length,
        content_type="text/markdown",
        metadata=integrity_metadata(
            sha256=digest,
            byte_length=length,
            metadata=metadata,
        ),
    )

    with pytest.raises(ArtifactValidationError, match="uploaded object"):
        verify_stored_object(intent, stored)


def test_self_review_is_strict_and_self_score_has_no_external_score_field() -> None:
    review = SelfReviewCommand(
        expected_version=3,
        main_answer="Recommend a rollback while preserving evidence.",
        did_well="Led with a decision.",
        structure_weakness="The risk section came late.",
        vague_points="I said soon instead of naming a checkpoint.",
        hesitation_points="I paused before the mitigation.",
        change_next="State the decision, evidence, risk, and next checkpoint.",
        self_score=3,
    )

    assert review.self_score == 3
    assert "rubric_score" not in SelfReviewCommand.model_fields
    with pytest.raises(ValueError):
        IncompleteCommand.model_validate(
            {
                "expected_version": 3,
                "classification": "useful",
                "self_score": 3,
            }
        )


def test_ai_processing_cannot_skip_mandatory_self_review() -> None:
    with pytest.raises(ActivityStateError, match="transition"):
        transition(
            current=ActivityState.OUTPUT_COMMITTED,
            target=ActivityState.AI_PROCESSING,
            actual_version=3,
            expected_version=3,
            day_type="weekday",
            day_status="in_progress",
        )


def test_attempt_b_inherits_exact_exercise_mapping_from_attempt_a_snapshot() -> None:
    attempt = Attempt(
        owner_id=1,
        activity_instance_id=1,
        attempt_kind="attempt_a",
        parent_attempt_id=None,
        original_text=(
            '{"contract_version":1,"task_context":'
            '{"exercise_type":"troubleshooting_case","mapping_version":"seed-v1"},'
            '"output":{"kind":"case"}}'
        ),
        original_markdown=None,
        original_sql=None,
        audience="Hiring manager",
        prompt="Investigate the incident.",
        assistance_mode="none",
        commitment_hash=b"a" * 32,
        committed_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    assert ActivityService._parent_evidence_mapping(attempt) == (
        "troubleshooting_case",
        "seed-v1",
    )
    attempt.original_text = "{}"
    with pytest.raises(ActivityConflict, match="mapping"):
        ActivityService._parent_evidence_mapping(attempt)
