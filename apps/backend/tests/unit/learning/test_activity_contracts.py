from __future__ import annotations

from copy import deepcopy

import pytest
from tamforge_backend.learning.contracts import (
    ContractContext,
    OutputContractError,
    validate_output_contract,
)

BASE = {
    "contract_version": 1,
    "prompt": "Explain the result to a technical customer.",
    "audience": "Technical customer",
    "time_limit_minutes": 45,
}


def _context(*, block: str, source_hidden: bool = False) -> ContractContext:
    return ContractContext(
        block=block,
        source_hidden=source_hidden,
        timebox_minutes=45,
        task_stable_id="m1-w1-d01-example",
        exercise_type="example_exercise",
        mapping_version="seed-v1",
        roadmap_version_key="month-1-v2",
        task_definition_id=12,
    )


@pytest.mark.parametrize(
    ("block", "source_hidden", "payload", "expected_kind"),
    [
        (
            "technical_learning",
            True,
            {
                **BASE,
                "kind": "reading",
                "key_ideas": [
                    "HTTP is stateless.",
                    "Retries need bounds.",
                    "Timeouts are budgets.",
                ],
                "boundary_or_failure": "A retry can amplify an outage.",
                "tam_customer_example": "Explain a 504 without blaming one service.",
                "unresolved_question": "Where is the end-to-end timeout enforced?",
            },
            "reading",
        ),
        (
            "sql",
            False,
            {
                **BASE,
                "kind": "sql",
                "query": "SELECT customer_id, SUM(amount) FROM payments GROUP BY customer_id",
                "result": "customer_id=7,total=120.00",
                "validation": "Compared row count and totals with the source table.",
                "explanation": "The query returns one row per customer.",
                "business_meaning": "It reconciles captured value by customer.",
                "solving_seconds": 900,
                "assistance_used": "none",
            },
            "sql",
        ),
        (
            "tam_case",
            False,
            {
                **BASE,
                "kind": "case",
                "canonical_prompt": "A customer's payments are intermittently duplicated.",
                "canonical_facts": ["Duplicates began after a retry change."],
                "discovery_questions": ["Which idempotency key is sent?"],
                "assumptions": ["The customer retries after a timeout."],
                "working_notes": "Separate transport retries from business deduplication.",
                "final_artifact": "Investigation plan and customer update.",
                "decisions": ["Inspect idempotency storage before changing retry policy."],
                "risks": ["Disabling retries may reduce successful captures."],
                "unresolved_questions": ["Does every client persist the same key?"],
            },
            "case",
        ),
        (
            "communication_spoken",
            False,
            {
                **BASE,
                "kind": "writing",
                "requested_action": "Approve a controlled retry rollback.",
                "facts": ["Duplicate rate increased after release 42."],
                "unknowns": ["Whether older clients omit idempotency keys."],
                "tone": "Direct and calm",
                "word_or_character_limit": "150 words",
                "draft_markdown": (
                    "We recommend rolling back the retry change while we verify "
                    "idempotency coverage."
                ),
                "self_edit_notes": "Removed speculation and led with the requested decision.",
            },
            "writing",
        ),
        (
            "career_pipeline",
            False,
            {
                **BASE,
                "kind": "pipeline",
                "company": "ExampleCo",
                "role": "Technical Account Manager",
                "stage": "Applied",
                "completed_action": "Submitted a tailored application.",
                "artifact_summary": "Saved the role-specific résumé and application receipt.",
                "next_action": "Follow up with the hiring manager in five business days.",
            },
            "pipeline",
        ),
    ],
)
def test_every_universal_activity_contract_preserves_required_evidence(
    block: str,
    source_hidden: bool,
    payload: dict[str, object],
    expected_kind: str,
) -> None:
    result = validate_output_contract(
        payload,
        context=_context(block=block, source_hidden=source_hidden),
    )

    assert result.kind == expected_kind
    assert result.prompt == BASE["prompt"]
    assert result.audience == BASE["audience"]
    assert result.canonical_payload["contract_version"] == 1
    assert result.canonical_payload["task_context"] == {
        "task_definition_id": 12,
        "task_stable_id": "m1-w1-d01-example",
        "exercise_type": "example_exercise",
        "mapping_version": "seed-v1",
        "roadmap_version_key": "month-1-v2",
        "time_limit_minutes": 45,
    }
    assert result.canonical_payload["output"]["kind"] == expected_kind  # type: ignore[index]


def test_reading_requires_closed_source_recall_and_exactly_three_ideas() -> None:
    payload = {
        **BASE,
        "kind": "reading",
        "key_ideas": ["One", "Two", "Three"],
        "boundary_or_failure": "Boundary",
        "tam_customer_example": "Example",
        "unresolved_question": "Question",
    }

    with pytest.raises(OutputContractError, match="source must be hidden"):
        validate_output_contract(payload, context=_context(block="technical_learning"))

    payload["key_ideas"] = ["One", "Two"]
    with pytest.raises(OutputContractError, match="3 items"):
        validate_output_contract(
            payload,
            context=_context(block="technical_learning", source_hidden=True),
        )


@pytest.mark.parametrize(
    ("block", "payload_update", "message"),
    [
        (
            "sql",
            {
                "kind": "sql",
                "query": "SELECT 1",
                "result": "1",
                "validation": " ",
                "explanation": "One row.",
                "business_meaning": "Connectivity check.",
                "solving_seconds": 10,
                "assistance_used": "none",
            },
            "non-blank",
        ),
        (
            "tam_case",
            {
                "kind": "case",
                "canonical_prompt": "Case",
                "canonical_facts": [],
                "discovery_questions": ["Question"],
                "assumptions": ["Assumption"],
                "working_notes": "Notes",
                "final_artifact": "Artifact",
                "decisions": ["Decision"],
                "risks": ["Risk"],
                "unresolved_questions": ["Unknown"],
            },
            "at least 1 item",
        ),
        (
            "communication_spoken",
            {
                "kind": "writing",
                "requested_action": "Action",
                "facts": ["Fact"],
                "unknowns": ["Unknown"],
                "tone": "Calm",
                "word_or_character_limit": "100 words",
                "draft_markdown": "Draft",
                "self_edit_notes": " ",
            },
            "non-blank",
        ),
        (
            "career_pipeline",
            {
                "kind": "pipeline",
                "company": "ExampleCo",
                "role": "TAM",
                "stage": "Applied",
                "completed_action": " ",
                "artifact_summary": "Receipt",
                "next_action": "Follow up",
            },
            "non-blank",
        ),
    ],
)
def test_contracts_reject_missing_or_blank_required_evidence(
    block: str,
    payload_update: dict[str, object],
    message: str,
) -> None:
    payload = deepcopy(BASE)
    payload.update(payload_update)
    with pytest.raises(OutputContractError, match=message):
        validate_output_contract(payload, context=_context(block=block))


def test_contract_rejects_wrong_task_type_or_time_limit() -> None:
    pipeline = {
        **BASE,
        "kind": "pipeline",
        "company": "ExampleCo",
        "role": "TAM",
        "stage": "Applied",
        "completed_action": "Submitted application",
        "artifact_summary": "Receipt",
        "next_action": "Follow up",
    }
    with pytest.raises(OutputContractError, match="not allowed"):
        validate_output_contract(pipeline, context=_context(block="sql"))

    pipeline["time_limit_minutes"] = 30
    with pytest.raises(OutputContractError, match="time limit"):
        validate_output_contract(pipeline, context=_context(block="career_pipeline"))
